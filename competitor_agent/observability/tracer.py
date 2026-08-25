"""链路追踪 — 自研 trace→span 树底座 + 可选 Langfuse exporter 入口（设计文档 54）

背景：现有可观测性（``observability/logger.py`` 会话 JSON 日志 + ``llm/client._log_call``
埋点）是**扁平事件流**——无 trace→span 树、工具调用无结构化 span、无 trace 级聚合、
无平台化上报。设计文档 54 拍板：**自研轻量 trace 总线为底座 + Langfuse 作可选 exporter**
（数据模型对齐 Langfuse 概念，三环境变量齐全才启用上报）；Q2 span 三档全要
（llm.call generation / tool.call / diff-thread 子 Agent 嵌套 span）；Q3 查看方式 =
CLI ``trace show <sid>`` 文本瀑布图 + JSONL 落盘。

本模块为自研底座（零依赖），``Trace / Span / Generation`` 模型对齐 Langfuse：

.. code-block:: text

    Trace(entity=根, trace_id=session_id, name="analyze", 聚合 total_cost/total_tokens)
    Span{kind: phase|tool|subagent} → 挂 parent
    Generation = Span 特化 kind=llm：+ model/tokens/cost/latency/attempts/retried

落盘：``<data_dir>/traces/<YYYY-MM-DD>.jsonl``，每行一条 span 完成记录
（含 trace_id/parent_span_id），按 trace 过滤重建树。脱敏纪律沿用 ``_log_call``——
不落 prompt 全文、不落密钥，input/output_brief 截断 200 字符。
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from collections import defaultdict, deque
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from competitor_agent.secret_vault import get_data_dir

logger = logging.getLogger("competitor_agent.observability.tracer")

# span 种类：与设计文档 §2.1 数据模型对齐
KIND_TRACE = "trace"  # 根
KIND_PHASE = "phase"  # analyze / delegate 等阶段
KIND_TOOL = "tool"  # tool.call
KIND_SUBAGENT = "subagent"  # 子 Agent
KIND_LLM = "llm"  # generation（Span 特化）

# input/output_brief 截断长度（脱敏纪律，与设计文档 §2.1 一致）
_BRIEF_MAX = 200

SUCCESS = "ok"
ERROR = "error"
CANCELLED = "cancelled"


def _now() -> str:
    """UTC 毫秒级 ISO 时间戳（用于 span start/end 与 JSONL 按日切文件）。"""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _brief(text: Any) -> str:
    """把任意 brief 输入规整为单行截断字符串（200 字符），不落敏感全文。"""
    if text is None:
        return ""
    s = str(text).replace("\n", " ").replace("\r", " ").strip()
    return s[:_BRIEF_MAX]


class SpanSink(Protocol):
    """span 完成记录的下游：默认 JsonlSink，可选 LangfuseExporter。"""

    def emit(self, record: dict[str, Any]) -> None: ...


class JsonlSink:
    """原子追加写 JSONL：``<traces_dir>/<YYYY-MM-DD>.jsonl``，每行一条 span 记录。

    与 ``core/checkpoint`` 的 ``JsonStore`` 同纪律（追加写 + flush，不落地临时文件），
    但 span 是 append-only 事件流（无回写需求），直接追加即可。
    """

    def __init__(self, traces_dir: Path | None = None) -> None:
        self._dir = Path(traces_dir) if traces_dir is not None else get_data_dir() / "traces"
        self._lock = threading.Lock()

    @property
    def traces_dir(self) -> Path:
        return self._dir

    def _path_for(self, ts: str) -> Path:
        return self._dir / f"{ts[:10]}.jsonl"

    def emit(self, record: dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        path = self._path_for(str(record.get("start") or _now()))
        with self._lock, path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


class Tracer:
    """trace→span 树自研底座。

    - **线程局部 span 栈**：同线程嵌套自动挂 parent（Lead/子 Agent 线程内 LLM 与
      ``tool.call`` 自动成为当前 span 的子节点）；
    - **跨线程显式传 parent_span_id**：子 Agent 经 ``DelegateRunner`` 后台线程执行，
      通过 ``start_trace``/``span(trace_id=..., parent_span_id=...)`` 显式挂接；
    - ``unhandled`` tool 的跨线程 parent 传递：``dispatch`` 在 Lead 线程把
      ``(trace_id, tool_span_id)`` 压入待领取上下文，``delegate`` 在后台线程领取
      （单 Lead 线程串行 dispatch 时栈顶即正确父节点）。
    """

    def __init__(self, sinks: list[SpanSink] | None = None) -> None:
        self._sinks: list[SpanSink] = list(sinks) if sinks is not None else [JsonlSink()]
        self._local = threading.local()
        self._traces: dict[str, dict[str, Any]] = {}  # trace_id -> 根（含聚合）
        self._lock = threading.Lock()
        # 跨线程 tool parent 待领取队列：有界（delegate 调用前仅会有最近若干工具 span，
        # 超限丢弃最旧的非消费条目，始终保留最新——delegate 自己的 ctx 是最新的不会被剪）
        self._pending_tool_ctx: deque[tuple[str | None, str | None]] = deque(maxlen=256)

    # ── 线程局部 span 栈 ────────────────────────────────────────────────

    def _stack(self) -> list[dict[str, str]]:
        st = getattr(self._local, "span_stack", None)
        if st is None:
            st = self._local.span_stack = []
        return st

    def current_trace_id(self) -> str | None:
        """当前线程栈顶所归属的 trace_id（无活动 trace 返回 None）。"""
        st = self._stack()
        return st[0]["trace_id"] if st else None

    def current_span_id(self) -> str | None:
        """当前线程最近的未闭合 span_id（用于自动挂 parent）。"""
        st = self._stack()
        return st[-1]["span_id"] if st else None

    # ── 生命周期 ────────────────────────────────────────────────────────

    def start_trace(
        self,
        name: str = "analyze",
        *,
        trace_id: str | None = None,
        input_brief: Any = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """开启一个 trace（根 span），返回 trace_id。

        ``trace_id`` 缺省时自生成；业务侧把 ``session_id`` 显式传入，使
        ``trace == session_id``（零新 ID 体系，设计文档 §1.3）。

        线程安全：注册表由锁保护，跨线程（子 Agent）的 generation 累加都更新同一根。
        """
        trace_id = trace_id or f"sess_{uuid.uuid4().hex[:8]}"
        now = _now()
        root: dict[str, Any] = {
            "name": name,
            "kind": KIND_TRACE,
            "trace_id": trace_id,
            "span_id": trace_id,  # 根 span_id 复用 trace_id，便于重建树
            "parent_span_id": None,
            "start": now,
            "end": None,
            "status": SUCCESS,
            "input_brief": _brief(input_brief),
            "output_brief": "",
            "error": None,
            "metadata": metadata or {},
            # 内部聚合位：generation 完成时累加，end_trace 时并入根记录
            "_total_tokens": 0,
            "_total_cost": 0.0,
        }
        with self._lock:
            self._traces[trace_id] = root
        # 根入当前线程栈（Lead 线程），使后续 start_span 自动挂根下
        self._stack().append({"trace_id": trace_id, "span_id": trace_id})
        return trace_id

    def end_trace(
        self,
        trace_id: str,
        *,
        status: str = SUCCESS,
        output_brief: Any = "",
        error: str | None = None,
    ) -> None:
        """闭合 trace：写入端/状态，聚合 total_cost/total_tokens，落盘后移除注册。"""
        with self._lock:
            root = self._traces.pop(trace_id, None)
        if root is None:
            return
        root["end"] = _now()
        root["status"] = status
        root["output_brief"] = _brief(output_brief)
        root["error"] = error
        root["total_tokens"] = root.pop("_total_tokens", 0)
        root["total_cost_usd"] = round(root.pop("_total_cost", 0.0), 6)
        self._emit(root)
        st = self._stack()
        if st and st[0].get("span_id") == trace_id:
            st.clear()

    @contextmanager
    def span(
        self,
        name: str,
        *,
        kind: str = KIND_PHASE,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        input_brief: Any = "",
        **extra: Any,
    ) -> Iterator[dict[str, Any] | None]:
        """开启一个子 span 上下文：with 块退出时按其 outcome 自动闭合。

        - 同线程嵌套：``parent_span_id`` 缺省取当前线程栈顶（自动挂 parent）；
        - 跨线程（子 Agent / delegate 后台）：显式传 ``trace_id`` + ``parent_span_id``；
        - 无活动 trace（未包在 ``start_trace`` 内）→ 零埋点 yield None（降级不炸）。
        """
        tid = trace_id or self.current_trace_id()
        parent = parent_span_id or self.current_span_id()
        if tid is None:
            yield None
            return
        span_id = uuid.uuid4().hex[:16]
        base: dict[str, Any] = {
            "name": name,
            "kind": kind,
            "trace_id": tid,
            "span_id": span_id,
            "parent_span_id": parent,
            "start": _now(),
            "end": None,
            "status": SUCCESS,
            "input_brief": _brief(input_brief),
            "output_brief": "",
            "error": None,
        }
        self._stack().append({"trace_id": tid, "span_id": span_id})
        try:
            yield base
        except BaseException as exc:
            base["status"] = ERROR
            base["error"] = _brief(f"{type(exc).__name__}: {exc}")
            self._end_span(base)
            raise
        else:
            self._end_span(base)
        finally:
            st = self._stack()
            if st and st[-1].get("span_id") == span_id:
                st.pop()

    def record_generation(
        self,
        *,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        elapsed_ms: int,
        cost_usd: float,
        attempts: int = 1,
        retried: bool = False,
        timed_out: bool = False,
        error: str | None = None,
    ) -> None:
        """LLM 调用即发即记的 generation span（``_log_call`` 挂 hook，数据同源）。

        挂到当前线程最近 span 下（Lead 线程 → Lead span；子 Agent 线程 → subagent span）。
        无活动 trace 时不记录（零埋点降级）。
        """
        tid = self.current_trace_id()
        if tid is None:
            return
        span: dict[str, Any] = {
            "name": "llm.call",
            "kind": KIND_LLM,
            "trace_id": tid,
            "span_id": uuid.uuid4().hex[:16],
            "parent_span_id": self.current_span_id(),
            "start": _now(),
            "end": _now(),
            "status": ERROR if error else SUCCESS,
            "input_brief": "",
            "output_brief": "",
            "error": _brief(error) if error else None,
            "model": model,
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "total_tokens": int(prompt_tokens or 0) + int(completion_tokens or 0),
            "elapsed_ms": int(elapsed_ms),
            "cost_usd": round(float(cost_usd or 0.0), 6),
            "attempts": int(attempts),
            "retried": bool(retried),
            "timed_out": bool(timed_out),
        }
        self._end_span(span)

    # ── 跨线程 tool parent 上下文（delegate 痛点：dispatch 在 Lead 线程、
    #    delegate 函数体在超时 worker 线程，需把父 span 显式带过去）─────────

    def push_tool_context(self, trace_id: str | None, parent_span_id: str | None) -> None:
        """dispatch 在 Lead 线程把当前 (trace_id, 工具 span id) 压入待领取上下文。"""
        with self._lock:
            self._pending_tool_ctx.append((trace_id, parent_span_id))

    def pop_tool_context(self) -> tuple[str | None, str | None]:
        """delegate 在后台线程领取父上下文（无则 None,None）。"""
        with self._lock:
            return self._pending_tool_ctx.pop() if self._pending_tool_ctx else (None, None)

    # ── 内部 ────────────────────────────────────────────────────────────

    def _end_span(self, span: dict[str, Any]) -> None:
        """收尾单个 span：聚合到根 + 落盘。generation 才参与 cost/token 聚合。"""
        span.setdefault("end", _now())
        if span.get("kind") == KIND_LLM:
            self._accumulate(span)
        self._emit(span)

    def _accumulate(self, span: dict[str, Any]) -> None:
        tid = span.get("trace_id")
        if not tid:
            return
        with self._lock:
            root = self._traces.get(tid)
            if root is None:
                return
            root["_total_tokens"] += int(span.get("total_tokens") or 0)
            root["_total_cost"] += float(span.get("cost_usd") or 0.0)

    def _emit(self, record: dict[str, Any]) -> None:
        for sink in self._sinks:
            try:
                sink.emit(record)
            except Exception:
                logger.warning("trace sink 写入失败: %s", type(sink).__name__, exc_info=True)


# ── 模块级单例 ──────────────────────────────────────────────────────────

_tracer: Tracer | None = None


def get_tracer() -> Tracer:
    """模块级单例（懒加载）；测试可显式构造 Tracer 注入，不依赖本单例。"""
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer


# ── JSONL 读取与重建（CLI trace show/list 用，纯本地零网络）─────────────


def traces_dir() -> Path:
    """trace JSONL 根目录（与 JsonlSink 默认一致）。"""
    return get_data_dir() / "traces"


def iter_traces(path: Path | None = None) -> list[dict[str, Any]]:
    """读取全部 JSONL 记录（每行一条 span 完成记录；文件不存在/空返回空列表）。"""
    base = Path(path) if path is not None else traces_dir()
    if not base.exists():
        return []
    records: list[dict[str, Any]] = []
    for file in sorted(base.glob("*.jsonl")):
        with file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def list_summaries(path: Path | None = None) -> list[dict[str, Any]]:
    """最近 trace 摘要（供 ``trace list``）：每个 trace 一行根记录 + 子 span 数。

    按 start 降序返回（最新在前）。
    """
    records = iter_traces(path)
    roots: list[dict[str, Any]] = []
    children: dict[str, int] = defaultdict(int)
    seen: set[str] = set()
    for r in records:
        tid = r.get("trace_id")
        if not tid:
            continue
        if r.get("kind") == KIND_TRACE and tid not in seen:
            # 根记录可能在 JSONL 里只出现一次（end_trace 落盘）；同一 trace 可能因
            # 多日切分有多个根，取最早一条即可（去重防重复展示）
            seen.add(tid)
            roots.append(r)
        children[tid] += 1
    for r in roots:
        r["span_count"] = children.get(r.get("trace_id") or "", 1) - 1  # 去掉根自身
    roots.sort(key=lambda r: str(r.get("start") or ""), reverse=True)
    return roots


def load_trace(trace_id: str, path: Path | None = None) -> list[dict[str, Any]]:
    """按 trace_id 读取全部 span 完成记录（含根），供瀑布渲染重建树。"""
    return [r for r in iter_traces(path) if r.get("trace_id") == trace_id]


def _children_by(spans: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    children: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in spans:
        children[str(s.get("parent_span_id") or "")].append(s)
    for values in children.values():
        values.sort(key=lambda s: str(s.get("start") or ""))
    return children


def _duration_ms(end: str | None, start: str | None) -> float:
    start = start or end
    end = end or start
    assert start is not None and end is not None
    try:
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end)
        return max(0.0, (e - s).total_seconds() * 1000)
    except (ValueError, TypeError):
        return 0.0


def render_waterfall(spans: list[dict[str, Any]]) -> str:
    """文本瀑布图：缩进树 + 相对耗时条 + 每行 model/tokens/cost/耗时列。

    根（kind=trace）为顶层行，其余按 parent 缩进；耗时条按 trace 总时长归一化
    （``█`` 数量 ∝ 占根时长比例）。
    """
    if not spans:
        return "（无 trace 数据）"
    children = _children_by(spans)
    roots = [s for s in spans if s.get("kind") == KIND_TRACE] or [
        # 无根时以 parent=None 的节点兜底
        s for s in spans if not s.get("parent_span_id")
    ]
    total_ms = max(_duration_ms(s.get("end"), s.get("start")) for s in spans) or 1.0
    # 实际每行 bar 长度按自身占比 × 40 格
    max_bars = 40

    def fmt_cost(s: dict[str, Any]) -> str:
        cost = s.get("cost_usd")
        if cost is None:
            return ""
        return f" ${float(cost):.4f}"

    def token_txt(s: dict[str, Any]) -> str:
        if s.get("kind") != KIND_LLM:
            return ""
        pt = int(s.get("prompt_tokens") or 0)
        ct = int(s.get("completion_tokens") or 0)
        return f" {pt + ct}k tok"

    lines: list[str] = []

    def visit(s: dict[str, Any], depth: int, is_last: bool, prefix: str) -> None:
        dms = _duration_ms(s.get("end"), s.get("start"))
        frac = dms / total_ms if total_ms else 0.0
        bars = "█" * max(0, round(frac * max_bars))
        label = str(s.get("name") or s.get("kind") or "span")
        st = s.get("status") or SUCCESS
        model = f" {s.get('model')}" if s.get("model") else ""
        ts = token_txt(s)
        cost = fmt_cost(s)
        connector = "└─ " if is_last else "├─ "
        lines.append(
            f"{prefix}{connector}{label}{model}"
            f"{ts}{cost}  {dms/1000:.1f}s {bars}"
            + (f"  [{st}]" if st != SUCCESS else "")
        )
        kid_indent = prefix + ("   " if is_last else "│  ")
        kids = children.get(str(s.get("span_id")), [])
        for i, child in enumerate(kids):
            visit(child, depth + 1, i == len(kids) - 1, kid_indent)

    for i, root in enumerate(roots):
        visit(root, 0, i == len(roots) - 1, "")
    return "\n".join(lines)


# 业务侧 span 结构标识 value_objects 复用（子模块无需再建模型）
TraceKindValues = (KIND_TRACE, KIND_PHASE, KIND_TOOL, KIND_SUBAGENT, KIND_LLM)

__all__ = [
    "CANCELLED",
    "ERROR",
    "KIND_LLM",
    "KIND_PHASE",
    "KIND_SUBAGENT",
    "KIND_TOOL",
    "KIND_TRACE",
    "SUCCESS",
    "JsonlSink",
    "SpanSink",
    "TraceKindValues",
    "Tracer",
    "get_tracer",
    "iter_traces",
    "list_summaries",
    "load_trace",
    "render_waterfall",
    "traces_dir",
]