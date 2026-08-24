"""delegate 工具 — 批量后台并发委派维度子 Agent（设计文档 49 §3.3）

仿 deer-flow ``task_tool.py`` + ``subagents/executor.py`` 的委派-回填模型：
Lead 调用 ``delegate`` → 一次性 spawn 指定维度子 Agent（后台线程池并发）→
阻塞轮询全部 terminal → 各结果（状态 + 截断正文）合并为一条回填文本，
作为工具 Observation 进入 Lead 会话，Lead 下一次 LLM 调用读到它继续决策。

*与 deer-flow 差异*：deer-flow 是 Lead 多轮多次 ``task()`` + 独立轮询
（fire-and-poll）；本项目同步 ReAct 循环一次解析一个 Action，故合并为
「批量 spawn + 一次轮询 + 合并回填」，保留「后台并发」实质，不引入
fire-and-poll 状态机。子 Agent 取消/超时逐维度标注，不影响其余。
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted
from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.delegate_tool")

_POLL_INTERVAL_SECONDS = 1.0
_DEFAULT_TIMEOUT_SECONDS = 60

_STATUS_LABELS = {
    "running": "执行中",
    "done": "完成",
    "error": "异常",
    "timed_out": "超时",
}


@dataclass
class SubagentRuntime:
    """一个可运行子 Agent 会话的包装（构建者由 facade 注入，避免 agent 层依赖 facade）。"""

    name: str
    run: Callable[[str], Any]  # (task) -> ReactRunResult（含 answer/steps/cancelled/budget_exhausted/transcript）


@dataclass
class _BackgroundRecord:
    """后台子 Agent 执行记录（注册表条目，仿 deer-flow ``_background_tasks[execution_id]``）。"""

    execution_id: str
    name: str
    task: str
    trace_id: str | None = None  # 设计文档 54：跨线程 subagent span 归属的 trace
    parent_span_id: str | None = None  # 设计文档 54：subagent span 挂在 delegate 下的父 span
    future: Future | None = None
    status: str = "running"
    result: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DelegateRunner:
    """后台线程池 + 执行注册表 + 轮询/清理（仿 deer-flow ``SubagentExecutor``）。"""

    def __init__(
        self,
        runtime_factory: Callable[[str], SubagentRuntime],
        max_concurrent: int = 3,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        tracer: Any = None,  # 设计文档 54：subagent span（None 用模块单例）
    ) -> None:
        self._runtime_factory = runtime_factory
        self._max_concurrent = max(1, int(max_concurrent))
        self._timeout_seconds = timeout_seconds
        self._pool = ThreadPoolExecutor(
            max_workers=self._max_concurrent, thread_name_prefix="subagent"
        )
        self._tasks: dict[str, _BackgroundRecord] = {}
        self._lock = threading.Lock()
        from competitor_agent.observability.tracer import get_tracer

        self._tracer = tracer if tracer is not None else get_tracer()

    def spawn(self, name: str, task: str) -> str:
        """提交一个子 Agent 到后台线程池，返回 execution_id（仿 execute_async）。"""
        execution_id = uuid.uuid4().hex[:12]
        # 跨线程 subagent span 归属：显式传参（delegate 工具提供）或从当前线程待领取
        # 上下文取（dispatch 在 Lead 线程压入，由本后台线程领取）。
        trace_id, parent_span_id = self._spawn_parent()
        rec = _BackgroundRecord(
            execution_id=execution_id,
            name=name,
            task=task,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
        )
        with self._lock:
            self._tasks[execution_id] = rec
        rec.future = self._pool.submit(self._run, name, task, rec)
        logger.info("子 Agent 已后台提交: %s (%s)", name, execution_id)
        return execution_id

    def spawn_with_parent(self, name: str, task: str, *, trace_id: str | None, parent_span_id: str | None) -> str:
        """带显式 trace 父节的提交（delegate 工具内：同一 delegate span 下的多个子 Agent 平行）。

        避免同一批子 Agent 各自 pop 不同父节，保证它们互为兄弟、挂在同一 delegate 下。
        """
        execution_id = uuid.uuid4().hex[:12]
        rec = _BackgroundRecord(
            execution_id=execution_id,
            name=name,
            task=task,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
        )
        with self._lock:
            self._tasks[execution_id] = rec
        rec.future = self._pool.submit(self._run, name, task, rec)
        logger.info("子 Agent 已后台提交: %s (%s)", name, execution_id)
        return execution_id

    def _spawn_parent(self) -> tuple[str | None, str | None]:
        """读取当前线程待领取的 (trace_id, parent_span_id)（无则 None,None）。"""
        if self._tracer is None:
            return None, None
        return self._tracer.pop_tool_context()

    def _run(self, name: str, task: str, rec: _BackgroundRecord) -> None:
        try:
            runtime = self._runtime_factory(name)
            if self._tracer is None:
                result = runtime.run(task)
            else:
                # 子 Agent 运行包在 kind=subagent span 里，并压入 worker 线程栈——
                # 使子 Agent 内的 llm.call / tool.call 自动挂到本 subagent span 下。
                with self._tracer.span(
                    name,
                    kind="subagent",
                    trace_id=rec.trace_id,
                    parent_span_id=rec.parent_span_id,
                    input_brief=task,
                ) as sub_span:
                    result = runtime.run(task)
            rec.result = getattr(result, "answer", "") or str(result)
            rec.status = "done"
            logger.info("子 Agent 完成: %s (%s)", name, rec.execution_id)
        except Exception as exc:  # noqa: BLE001 — 单子 Agent 失败不影响其余
            logger.warning("子 Agent 执行异常: %s (%s): %s", name, rec.execution_id, exc)
            rec.status = "error"
            rec.result = f"子 Agent 执行异常: {type(exc).__name__}: {exc}"

    def await_terminal(self, execution_id: str, timeout_seconds: float | None = None) -> _BackgroundRecord:
        """阻塞轮询直到子 Agent terminal（done/error/timed_out），返回记录。

        超时 → 标记 ``timed_out``（best-effort；后台 future 由其自身步数上限兜底结束，
        会话收尾 ``shutdown`` 统一回收线程池）。
        """
        rec = self._tasks.get(execution_id)
        if rec is None or rec.future is None:
            return rec
        timeout = timeout_seconds if timeout_seconds is not None else self._timeout_seconds
        try:
            rec.future.result(timeout=timeout)
        except TimeoutError:
            logger.warning("子 Agent 轮询超时: %s (%s)", rec.name, execution_id)
            rec.status = "timed_out"
            rec.result = rec.result or "子 Agent 执行超时"
        return rec

    def cleanup(self, execution_id: str) -> None:
        """terminal 后从注册表移除（防泄漏；后台 future 不中断）。"""
        with self._lock:
            self._tasks.pop(execution_id, None)

    def running_count(self) -> int:
        return len(self._tasks)

    def shutdown(self) -> None:
        """会话收尾：回收线程池（best-effort 取消未完成任务）。"""
        self._pool.shutdown(wait=False, cancel_futures=True)


def make_delegate_tool(
    runner: DelegateRunner,
    registry: Any | None = None,
) -> Callable[..., str]:
    """构造 delegate 工具函数（Lead 工具面注册用）。

    - ``registry``：SubagentRegistry（校验维度是否可委派；None 时不过滤）；
    - 工具签名 ``delegate(task, dimensions)``：批量 spawn 全部指定维度子 Agent
      （后台并发），轮询全部 terminal 后合并各结果（状态 + 截断正文）回填；
    - 设计文档 54：后台线程里先领取 dispatch 压入的 (trace_id, tool span) 上下文，
      包一层 ``delegate`` phase span，并让同一批子 Agent 共享该 span 作父节点。
    """
    from competitor_agent.agent.subagent_registry import get_subagent_registry

    registry = registry or get_subagent_registry()

    def _delegate_spawn_and_merge(
        dims: list[str],
        task: str,
        trace_id: str | None,
        parent_span_id: str | None,
        parallel: bool = True,
    ) -> str:
        """批量委派并合并回填。``parallel=True`` 全部 spawn 后统一 await（后台并发）；
        ``parallel=False`` 逐个 spawn+await（串行，供 Lead 表达"任务聚焦/预算有限"）。
        无论哪种节奏，单子 Agent 失败均不影响其余，结果按 dims 顺序合并。
        """
        merged: list[str] = []
        if parallel:
            execution_ids: list[str] = []
            for dim in dims:
                execution_ids.append(
                    runner.spawn_with_parent(
                        dim, f"{task}（请分析维度：{dim}）",
                        trace_id=trace_id, parent_span_id=parent_span_id,
                    )
                )
            for eid in execution_ids:
                rec = runner.await_terminal(eid)
                if rec is not None:
                    merged.append(_render_record(rec))
                    runner.cleanup(eid)
        else:
            for dim in dims:
                eid = runner.spawn_with_parent(
                    dim, f"{task}（请分析维度：{dim}）",
                    trace_id=trace_id, parent_span_id=parent_span_id,
                )
                rec = runner.await_terminal(eid)
                if rec is not None:
                    merged.append(_render_record(rec))
                    runner.cleanup(eid)
        return "\n\n".join(merged) if merged else "delegate 失败：全部子 Agent 无结果。"

    def delegate(
        dimensions: list[str],
        task: str = "",
        parallel: bool = True,
        reason: str = "",
    ) -> str:
        """通用委派（设计文档 62 M1）：``dimensions`` 既可是预注册维度、也可是候选竞品名。

        - ``parallel``：是否后台并发（Lead 决策；True=批量并发，False=串行逐个 await）；
          细节并发度不暴露，由 ``DelegateRunner.max_concurrent`` 默认接管（代码硬收敛）。
        - ``reason``：Lead 的调度意图说明（可观测，记入日志与 trace phase）。
        - ``registry``：校验/过滤可委派维度；未命中由 ``runtime_factory`` 按名构造
          （候选竞品子 Agent 由装配侧提供）。
        """
        dims = [d for d in (dimensions or []) if registry.get(d)]
        if not dims:
            available = ", ".join(registry.names())
            return (
                f"delegate 失败：未指定可委派维度（可用：{available}）。"
                "请给 dimensions 传数组，如 {\"dimensions\": [\"pricing\",\"feature\"]}。"
            )
        if reason:
            logger.info("delegate 调度意图（Lead）: parallel=%s reason=%s", parallel, reason)
        _brief = f"dimensions={','.join(dims)}; parallel={parallel}" + (f"; reason={reason}" if reason else "")
        tracer = getattr(runner, "_tracer", None)
        if tracer is None:
            return _delegate_spawn_and_merge(dims, task, None, None, parallel)
        trace_id, parent = tracer.pop_tool_context()
        if trace_id is None:
            # 无活动 trace：仍正常委派，只是不产生 subagent span（零埋点降级）
            return _delegate_spawn_and_merge(dims, task, None, None, parallel)
        with tracer.span(
            "delegate", kind="phase", trace_id=trace_id, parent_span_id=parent,
            input_brief=_brief,
        ) as dspan:
            parent_span = dspan["span_id"] if dspan is not None else parent
            return _delegate_spawn_and_merge(dims, task, trace_id, parent_span, parallel)

    return delegate


def _render_record(rec: _BackgroundRecord) -> str:
    """单个子 Agent 结果 → 回填文本（状态 + 截断正文，供 Lead 读取继续决策）。"""
    label = _STATUS_LABELS.get(rec.status, rec.status)
    body = (rec.result or "（空结果）")[:4000]
    return f"[维度子 Agent 结果: {rec.name} | 状态: {label}]\n{wrap_untrusted(body)}"
