"""ReActLoop — 带预算与事件流式产出的推理循环控制

与 ReactAgent 的关系：ReactAgent 是"单轮 LLM 对话工具"；
ReactLoop 负责跨轮次的预算控制、错误处理与 ProgressEvent 产出，
供 facade API / Web SSE 消费。

设计文档 43 §3.1：ReactLoop 统一会话上下文——与主流水线共享
取消（session_id）、预算（IterationBudget）、记忆/RAG 注入、事件（event_sink），
消除"ReAct 是旁路"的割裂。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.core.budget import IterationBudget
from competitor_agent.core.checkpoint import is_cancelled
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.llm.client import StreamDelta
from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.react_loop")


@dataclass
class ReactRunResult:
    """ReAct 一次运行的完整结果（含共享上下文状态，设计文档 43）"""

    answer: str
    steps: int = 0
    cancelled: bool = False
    budget_exhausted: bool = False
    transcript: list[dict] = field(default_factory=list)  # 工具步记录（设计文档 49 §3.5）


class ReactLoop:
    """包装 ReactAgent 的循环控制器（同步，M1 版）

    Args:
        agent: ReactAgent 实例
        max_steps: 最大推理步数
        event_sink: 进度事件回调
        session_id: 会话 ID（共享取消标志，None 不协作）
        budget: 迭代预算（共享步数/成本，None 不限制）
        memory_context_fn: (task) -> 记忆召回文本（设计文档 35 的 recent_context，None 跳过）
        rag_fn: (task) -> 知识库检索文本（None 跳过）
        system_prompt_override: 覆盖基础系统提示（Lead/子 Agent 专属提示 + skills，设计文档 49 §3.7）
        plan_first: 首步强制 make_plan（设计文档 49 §3.5）；规划结果存入 self.plan
        plan_sink: 可选自定义规划接收器（默认写 self.plan）
    """

    def __init__(
        self,
        agent: ReactAgent,
        max_steps: int | None = 6,
        event_sink: Callable[[ProgressEvent], None] | None = None,
        session_id: str | None = None,
        budget: IterationBudget | None = None,
        memory_context_fn: Callable[[str], str] | None = None,
        rag_fn: Callable[[str], str] | None = None,
        obs_max_chars: int | None = None,
        system_prompt_override: str | None = None,
        plan_first: bool = False,
        plan_sink: Callable[[str], None] | None = None,
        max_history_steps: int | None = None,  # 设计文档 56 Q4：配置化注入；None 用 ReactAgent 默认
        pinned_facts: list[str] | None = None,  # 设计文档 56 M2：已核验事实共享列表（压缩时重建 pinned 段）
        on_step: Callable[[dict], None] | None = None,  # transcript 捕获外的附加回调（pinned 收集等）
        stream_sink: Callable[[StreamDelta], None] | None = None,  # 设计文档 63 §5.5：仅 Lead 流式旁路
        final_as_payload: bool = True,  # 设计文档 64 §5.2：对话式分支 False → 最终文本走 Stream 通道
    ) -> None:
        self._agent = agent
        self._max_steps = max_steps
        self._event_sink = event_sink
        self._session_id = session_id
        self._budget = budget
        self._memory_context_fn = memory_context_fn
        self._rag_fn = rag_fn
        # 单条 Observation 截断上限（设计文档 46 §3.2）：None 用 ReactAgent 默认值
        self._obs_max_chars = obs_max_chars
        self._system_prompt_override = system_prompt_override
        self._plan_first = plan_first
        self._plan_sink = plan_sink
        self._max_history_steps = max_history_steps
        self._pinned_facts = pinned_facts
        self._on_step = on_step
        self._stream_sink = stream_sink
        self._final_as_payload = final_as_payload  # 设计文档 64 §5.2：对话式分支 False
        self.plan: dict | None = None  # make_plan 结果（供报告组装/记忆写侧）
        # 设计文档 62 §3.5：facade 装配侧挂载（非构造参数）——delegate 线程池与候选结果收集器
        self._delegate_runner: Any = None
        self._delegate_collector: dict[str, dict[str, Any]] = {}

    def run(self, task: str) -> str:
        """运行一次分析会话，返回最终结论文本（向后兼容：不携带取消/预算状态）。"""
        return self.run_with_result(task).answer

    def run_with_result(self, task: str) -> ReactRunResult:
        """带共享会话上下文运行：每步前取消/预算协作，记忆/RAG 注入系统提示。

        返回完整结果（结论文本 + 步数 + 取消/预算耗尽标志），供结构化产物消费。
        """
        system_prompt = self._agent.build_system_prompt(
            instructions=self._system_prompt_override or "",
            notes=self._memory_notes(task),
            knowledge=self._rag_knowledge(task),
        )
        self._emit(ProgressEvent(event="phase_start", phase="react", message="开始 ReAct 推理"))

        result = ReactRunResult(answer="")
        try:
            result.answer = self._agent.run(
                system_prompt,
                task,
                max_steps=self._max_steps,
                step_guard=self._step_guard(result),
                obs_max_chars=self._obs_max_chars,
                max_history_steps=self._max_history_steps,
                mandatory_first_tool="make_plan" if self._plan_first else None,
                first_tool_sink=self._on_plan,
                on_step=self._transcript_sink(result),
                pinned_facts=self._pinned_facts,
                stream_sink=self._stream_sink,
                final_as_payload=self._final_as_payload,
            )
            # 取消/预算中断时 ReactAgent 返回"已达最大步数"，此处覆盖为准确终止文案
            if result.cancelled:
                result.answer = "推理已取消（会话被中断）。"
                self._emit(
                    ProgressEvent(event="cancelled", phase="react", message="ReAct 推理已取消")
                )
            elif result.budget_exhausted:
                result.answer = "推理已停止（预算耗尽）。"
                self._emit(
                    ProgressEvent(event="error", phase="react", message="ReAct 推理预算耗尽")
                )
        except LLMUnavailableError as exc:
            logger.warning("LLM 不可用，ReAct 无法执行: %s", exc)
            result.answer = "LLM 服务不可用，跳过 ReAct 推理。"
            self._emit(ProgressEvent(event="error", phase="react", message=str(exc)))
        self._emit(ProgressEvent(event="phase_complete", phase="react", message="ReAct 推理完成"))
        return result

    def run_subagent(self, task: str) -> ReactRunResult:
        """运行一个子 Agent 会话（设计文档 49 §3.5）：复用 run_with_result 语义。

        子 Agent 不强制 make_plan（任务直接给定），独立预算/会话、共享取消/memory/RAG。
        """
        return self.run_with_result(task)

    def _transcript_sink(self, result: ReactRunResult) -> Callable[[dict], None]:
        """on_step 组合：transcript 捕获 + 附加回调（设计文档 56 M2 pinned 收集）。

        附加回调异常不冒泡（收集失败不影响推理循环；ReactAgent 侧亦有兜底）。
        """
        extra = self._on_step

        def _sink(rec: dict) -> None:
            result.transcript.append(rec)
            if extra is not None:
                try:
                    extra(rec)
                except Exception:
                    logger.warning("ReAct on_step 附加回调失败", exc_info=True)

        return _sink

    def _on_plan(self, plan_text: str) -> None:
        """make_plan 结果接收器：尝试解析为 dict 存入 self.plan（供报告组装/记忆写侧）。

        解析失败/非 dict 时 self.plan 保持 None（report 侧按无有效 plan → partial）。
        """
        import json

        try:
            parsed = json.loads(plan_text)
        except (json.JSONDecodeError, TypeError):
            logger.warning("make_plan 结果非 JSON，plan 未记录: %s", plan_text[:80])
            self.plan = None
            return
        # 设计文档 62 §3.1：单竞品 plan 用 competitor，多竞品 plan 用 competitors；
        # discovery 候选枚举前可仅带 resolution（候选后 web_tool 枚举，组装侧据此分型）
        if isinstance(parsed, dict) and (
            parsed.get("competitor") or parsed.get("competitors") or parsed.get("resolution")
        ):
            self.plan = parsed
        else:
            logger.warning("make_plan 结果缺 competitor/competitors/resolution，plan 未记录")
            self.plan = None

    def _step_guard(self, result: ReactRunResult) -> Callable[[], bool] | None:
        """每步前置检查：先取消、后预算。返回 False 提前终止循环。

        取消/预算均为可选（未注入时跳过对应检查），但步数计数始终生效——
        ``result.steps`` 供上层迭代/token 记账（Lead 无预算时仍累计真实步数）。
        """
        if self._session_id is None and self._budget is None:
            # 既无取消也无预算约束：仅需步数计数，仍返回 guard 递增 steps
            def count_only() -> bool:
                result.steps += 1
                return True

            return count_only

        def guard() -> bool:
            if self._session_id and is_cancelled(self._session_id):
                logger.info("会话 %s 已取消，中断 ReAct 循环", self._session_id)
                result.cancelled = True
                return False
            if self._budget is not None and not self._budget.consume():
                logger.warning("ReAct 预算耗尽，中断推理循环")
                result.budget_exhausted = True
                return False
            result.steps += 1
            return True

        return guard

    def _memory_notes(self, task: str) -> list[str] | None:
        """记忆召回（设计文档 35）：注入为系统提示的历史经验笔记；失败静默降级。"""
        if self._memory_context_fn is None:
            return None
        try:
            ctx = self._memory_context_fn(task)
        except Exception:
            logger.warning("ReAct 记忆注入失败", exc_info=True)
            return None
        return [ctx] if ctx else None

    def _rag_knowledge(self, task: str) -> list[str] | None:
        """RAG 检索（设计文档 02/32）：注入为知识库参考片段；失败静默降级。"""
        if self._rag_fn is None:
            return None
        try:
            ctx = self._rag_fn(task)
        except Exception:
            logger.warning("ReAct RAG 注入失败", exc_info=True)
            return None
        return [ctx] if ctx else None

    def _emit(self, event: ProgressEvent) -> None:
        if self._event_sink is not None:
            self._event_sink(event)
