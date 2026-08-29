"""设计文档 63 M2 — 仅 Lead 流式旁路 Web 端回归测试。

覆盖两件事：
① 真实 Lead 流式增量（thinking_delta/text_delta）经 stream_sink 进入 SSE 流，
   message_id 归位到 lead_id，payload.delta 为逐增量文本；
② 子 Agent 事件过滤（主旨2）：子 Agent 的 phase_start/phase_complete/progress
   不入 Lead 气泡（Web 层不把它们收敛为 text_delta）。
"""
from __future__ import annotations

import asyncio
import json

import pytest
from competitor_agent import web_app
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.domain_types.report import CompetitorReport


class StreamingLeadAPI:
    """模拟 Lead 流式 ReAct：经 stream_sink 发 thinking/text 增量后返回正常报告。"""

    def __init__(self, *args, **kwargs) -> None:
        self.event_sink = kwargs.get("event_sink")
        self.stream_sink = kwargs.get("stream_sink")

    def run(self, task: str, *, session_id: str | None = None) -> CompetitorReport:
        from competitor_agent.llm.client import StreamDelta

        # 与生产一致：Lead 在 run_in_executor 工作线程内经 stream_sink 投递流式增量
        self.stream_sink(StreamDelta(kind="thinking", text="先制定采集路线…"))
        self.stream_sink(StreamDelta(kind="text", text="分析 Cursor"))
        # 事件桥：Lead 循环仍有粗粒度叙述事件（会收敛为 text_delta）
        self.event_sink(
            ProgressEvent(event="progress", phase="react", progress=0.5, message="工具步推进")
        )
        return CompetitorReport(
            competitor=Competitor(name="cursor"),
            dimension_results=[],
            terminal_state="success",
            overall_confidence=0.8,
            markdown_report="# Cursor 报告\n流式验证",
        )

    def cancel(self, session_id: str) -> None:
        pass


def _patch_env(monkeypatch: pytest.MonkeyPatch, api_cls, tmp_memory) -> None:
    monkeypatch.setattr(web_app, "CompetitorAnalysisAPI", api_cls)
    monkeypatch.setattr(web_app, "LLMClient", lambda **kwargs: object())
    monkeypatch.setattr(web_app, "_get_memory", lambda: tmp_memory)
    monkeypatch.setattr(web_app, "save_report_markdown", lambda *a, **k: None)


def _collect(sse_lines: list[str]) -> list[dict]:
    return [
        json.loads(line[len("data: ") :])
        for line in sse_lines
        if line.startswith("data: ")
    ]


def test_lead_streaming_deltas_reach_sse(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """① Lead 流式增量（thinking/text）进入 SSE 且 message_id 归位 lead。"""
    from competitor_agent.memory import FourLayerMemory

    _patch_env(monkeypatch, StreamingLeadAPI, FourLayerMemory(tmp_path / "memory"))
    sid = "sess_m2_stream"
    web_app._sessions[sid] = {"task": "分析 Cursor", "cancelled": False}

    async def _run() -> list[str]:
        sse_lines: list[str] = []
        async for line in web_app._event_generator(sid, "分析 Cursor"):
            sse_lines.append(line)
        return sse_lines

    try:
        sse_lines = asyncio.run(_run())
    finally:
        web_app._sessions.pop(sid, None)

    events = _collect(sse_lines)
    kinds = [e["event"] for e in events]

    # message.start 唯一且 source=lead
    starts = [e for e in events if e["event"] == "message.start"]
    assert len(starts) == 1
    lead_id = starts[0]["payload"]["message_id"]

    # 流式增量：thinking_delta / text_delta 原样透传（不落入 _NARRATIVE 收敛分支）
    think = [e for e in events if e["event"] == "thinking_delta"]
    text = [e for e in events if e["event"] == "text_delta"]
    assert [t["payload"]["delta"] for t in think] == ["先制定采集路线…"]
    assert [t["payload"]["delta"] for t in text] == ["分析 Cursor", "工具步推进"]
    # message_id 贯穿一致
    for e in think + text:
        assert e["payload"]["message_id"] == lead_id
    # 叙述型工具步消息也被收敛为 text_delta 归位同一气泡
    assert "tool_step" not in kinds  # 无独立事件行，统一进 text_delta

    # 消息信封收口
    assert kinds.index("message.start") < kinds.index("thinking_delta")
    assert kinds.index("text.stop") < kinds.index("message.stop")
    assert [s["payload"]["final"] for s in events if s["event"] == "text.stop"][-1] is True


class IdleAPI:
    """模拟 Lead 长时间无事件（仅后台计算，无中途进度），验证心跳保活。"""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def run(self, task: str, *, session_id: str | None = None) -> CompetitorReport:
        import time

        time.sleep(0.6)  # 空转无事件 → 队列持续为空，触发心跳
        return CompetitorReport(
            competitor=Competitor(name="cursor"),
            dimension_results=[],
            terminal_state="success",
            overall_confidence=0.8,
            markdown_report="# Cursor 报告\n心跳验证",
        )

    def cancel(self, session_id: str) -> None:
        pass


def test_heartbeat_keepalive_during_idle(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """设计文档 63 §4.3：空闲队列空挂起超时到点发 `: keep-alive` 心跳（节流间隔）。"""
    from competitor_agent.memory import FourLayerMemory

    _patch_env(monkeypatch, IdleAPI, FourLayerMemory(tmp_path / "memory"))
    # 缩短心跳间隔以便测试（生产 10s）
    monkeypatch.setattr(web_app, "_HEARTBEAT_INTERVAL", 0.3)
    sid = "sess_heartbeat"
    web_app._sessions[sid] = {"task": "分析 Cursor", "cancelled": False}

    async def _run() -> list[str]:
        sse_lines: list[str] = []
        async for line in web_app._event_generator(sid, "分析 Cursor"):
            sse_lines.append(line)
        return sse_lines

    try:
        sse_lines = asyncio.run(_run())
    finally:
        web_app._sessions.pop(sid, None)

    heartbeats = [ln for ln in sse_lines if ln == ": keep-alive\n\n"]
    assert heartbeats, "空闲队列应发出 SSE 心跳保活"
    # 心跳是注释事件，不产生 event（_collect 的 data: 行不受影响）
    assert _collect(sse_lines)
    assert len(heartbeats) >= 1


def test_subagent_narrative_filtered_not_text_delta(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """② 主旨2 验证：子 Agent 的叙述事件经 _subagent_event_sink 过滤后不入 Lead 气泡。

    直接测模块级过滤 helper：phase_start/phase_complete/progress 被丢弃，
    诊断事件（error/cancelled）透传。
    """
    from competitor_agent.facade.api import _subagent_event_sink

    seen: list[ProgressEvent] = []
    sink = _subagent_event_sink(seen.append)

    sink(ProgressEvent(event="phase_start", phase="react", message="子 Agent 开始"))
    sink(ProgressEvent(event="phase_complete", phase="react", message="子 Agent 完成"))
    sink(ProgressEvent(event="progress", phase="react", progress=0.3, message="进度"))
    sink(ProgressEvent(event="error", phase="react", message="子 Agent 出错"))
    sink(ProgressEvent(event="cancelled", phase="react", message="取消"))

    assert [e.event for e in seen] == ["error", "cancelled"], "子 Agent 思考事件应被过滤"


class ChatAPI:
    """模拟对话式分支（设计文档 64 §5）：run() 返回 ChatResult（无报告面板）。"""

    def __init__(self, *args, **kwargs) -> None:
        self.event_sink = kwargs.get("event_sink")
        self.stream_sink = kwargs.get("stream_sink")

    def run(self, task: str, *, session_id: str | None = None):
        from competitor_agent.domain_types.report import ChatResult
        from competitor_agent.llm.client import StreamDelta

        # 对话答案经 Stream 通道（text_delta/thinking_delta）呈现
        self.stream_sink(StreamDelta(kind="text", text="你好！我是竞品情报助手。", turn=0))
        self.event_sink(ProgressEvent(event="phase_start", phase="react", message="对话"))
        return ChatResult(answer="你好！我是竞品情报助手。")

    def cancel(self, session_id: str) -> None:
        pass


def test_chat_result_no_report_panel(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """设计文档 64 §5：对话式分支只出会话消息，不发 report 事件、无报告面板。"""
    from competitor_agent.memory import FourLayerMemory

    _patch_env(monkeypatch, ChatAPI, FourLayerMemory(tmp_path / "memory"))
    sid = "sess_chat_64"
    web_app._sessions[sid] = {"task": "你好", "cancelled": False}

    async def _run() -> list[str]:
        sse_lines: list[str] = []
        async for line in web_app._event_generator(sid, "你好"):
            sse_lines.append(line)
        return sse_lines

    try:
        sse_lines = asyncio.run(_run())
    finally:
        web_app._sessions.pop(sid, None)

    events = _collect(sse_lines)
    kinds = [e["event"] for e in events]

    # 对话答案经 text_delta 呈现（含 turn），无 report / 无 message.start 面板信封之外的收敛
    assert "text_delta" in kinds
    assert any(e["payload"].get("turn") == 0 for e in events if e["event"] == "text_delta")
    # 无报告面板事件
    assert "report" not in kinds
    # 消息信封收口：message.stop 排在最后
    assert kinds.index("message.stop") == len(kinds) - 1
    stop = next(e for e in events if e["event"] == "message.stop")
    assert stop["payload"]["summary"]