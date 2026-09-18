"""设计文档 64 §5 — 对话式分支残留单测（doc 96 迁移中）。

覆盖：
③ web_app._stream_sink 透传 turn（§3.4 分段段号）。
（①意图门控/②对话式分支已随 parse_task 退役迁移至 test_conversation_entry_96.py；
本文件余项待 doc 96 Task 8 迁往 test_web_m2_streaming.py 后整文件删除。）
"""
from __future__ import annotations

import json

from competitor_agent.domain_types.report import CompetitorReport
from competitor_agent.llm.client import StreamDelta


class TestStreamSinkTurn:
    def test_stream_sink_forwards_turn(self, monkeypatch, tmp_path):
        """§3.4：web_app._event_generator 的 Lead 流式旁路把 delta.turn 透传进 SSE payload。"""
        import asyncio

        from competitor_agent import web_app
        from competitor_agent.domain_types.competitor import Competitor
        from competitor_agent.domain_types.report import CompetitorReport
        from competitor_agent.memory import FourLayerMemory

        class TurnLeadAPI:
            def __init__(self, *args, **kwargs) -> None:
                self.stream_sink = kwargs.get("stream_sink")

            def run(
                self,
                task: str,
                *,
                session_id: str | None = None,
                history_messages: list[dict[str, str]] | None = None,
            ) -> CompetitorReport:
                self.stream_sink(StreamDelta(kind="thinking", text="思考段0", turn=0))
                self.stream_sink(StreamDelta(kind="text", text="正文段0", turn=0))
                self.stream_sink(StreamDelta(kind="thinking", text="思考段1", turn=1))
                return CompetitorReport(
                    competitor=Competitor(name="cursor"),
                    dimension_results=[],
                    terminal_state="success",
                    overall_confidence=0.8,
                    markdown_report="# Cursor 报告",
                )

            def cancel(self, session_id: str) -> None:
                pass

        monkeypatch.setattr(web_app, "CompetitorAnalysisAPI", TurnLeadAPI)
        monkeypatch.setattr(web_app, "LLMClient", lambda **kwargs: object())
        monkeypatch.setattr(web_app, "_get_memory", lambda: FourLayerMemory(tmp_path / "memory"))
        monkeypatch.setattr(web_app, "save_report_markdown", lambda *a, **k: None)

        sid = "sess_turn_64"
        web_app._sessions[sid] = {"task": "x", "cancelled": False}

        async def _run() -> list[dict]:
            sse_lines = []
            async for line in web_app._event_generator(sid, "x"):
                sse_lines.append(line)
            events = [
                json.loads(line[len("data: "):])
                for line in sse_lines
                if line.startswith("data: ")
            ]
            return events

        try:
            events = asyncio.run(_run())
        finally:
            web_app._sessions.pop(sid, None)

        think = [e for e in events if e["event"] == "thinking_delta"]
        text = [e for e in events if e["event"] == "text_delta"]
        # turn 段号随增量透传到前端（分段思考渲染依据）
        assert [(e["payload"]["turn"]) for e in think] == [0, 1]
        assert [(e["payload"]["turn"]) for e in text] == [0]
        assert all("turn" in e["payload"] for e in think + text)
