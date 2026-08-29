"""设计文档 64 §5 — 意图门控（CHAT 决议 + 对话式分支）单测。

覆盖：
① run()/analyze() 入口：普通提问（parse_task 判定 chat）→ ChatResult（无报告面板）；
   分析类请求 → 照旧 CompetitorReport / ComparisonReport（回归）。
② 对话式分支：plan_first=False + 对话系统提示 + final_as_payload=False，
   答案经正文呈现；不 assemble、不发 report 事件。
③ web_app._stream_sink 透传 turn（§3.4 分段段号）。
"""
from __future__ import annotations

import json

from competitor_agent.domain_types.report import ChatResult, CompetitorReport
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.llm.client import LLMClient, StreamDelta, ToolCallReply


class ChatScriptedLLM:
    """脚本化 mock：parse 阶段判 chat，对话循环直接回 prose 最终答案。"""

    def complete(self, messages, model=None, **kwargs):
        # parse_task 的系统提示含「语义解析器」；普通对话循环则直接给答案
        system = str(messages[0].get("content", "")) if messages else ""
        if "语义解析器" in system:
            return json.dumps(
                {"resolution": "chat", "competitors": [], "dimensions": None, "custom_sources": {}}
            )
        return "你好！我是竞品情报助手，有什么可以帮你？"

    def __call__(self, messages, model=None, **kwargs):
        # complete_with_tools 非流式路径（tools kwarg 出现）→ 直接 ToolCallReply
        if kwargs.get("tools") is not None:
            return ToolCallReply(content="你好！我是竞品情报助手，有什么可以帮你？")
        return self.complete(messages, model=model, **kwargs)


class FakeExtractor:
    def fetch(self, gap, context):
        from competitor_agent.domain_types import Observation, SourceEvidence

        url = str(context.kwargs.get("url"))
        ev = SourceEvidence(source_name="web_extractor", url=url, content_hash=str(hash(url)), trust_level=0.9)
        return Observation(gap_field=str(getattr(gap, "field", "")), source="web_extractor", raw_text="x", evidence=ev)


def _chat_api(**kwargs) -> CompetitorAnalysisAPI:
    return CompetitorAnalysisAPI(
        extractor=FakeExtractor(),
        llm=LLMClient(call_func=ChatScriptedLLM()),
        use_llm=True,
        **kwargs,
    )


class TestChatGate:
    def test_run_plain_question_returns_chat_result(self):
        api = _chat_api()
        result = api.run("今天天气怎么样")
        assert isinstance(result, ChatResult)
        # 对话式分支：答案来自正文流（chat system prompt 下 Lead 直接 prose 收尾）
        assert result.answer
        assert not isinstance(result, CompetitorReport)

    def test_analyze_plain_question_returns_chat_result(self):
        api = _chat_api()
        result = api.analyze("介绍一下你自己")
        assert isinstance(result, ChatResult)

    def test_run_chat_emits_no_report_event(self):
        events = []
        api = _chat_api(event_sink=events.append)
        result = api.run("你好")
        assert isinstance(result, ChatResult)
        assert not any(e.event == "report" for e in events)

    def test_run_analysis_still_returns_report(self, mock_llm):
        """回归：分析类请求不受影响，照旧 CompetitorReport（意图门控只拦 chat）。"""
        api = CompetitorAnalysisAPI(
            extractor=FakeExtractor(), llm=mock_llm, use_llm=True
        )
        report = api.run("分析 Cursor")
        assert isinstance(report, CompetitorReport)
        assert report.competitor.name == "cursor"

    def test_run_chat_uses_chat_loop_not_make_plan(self, monkeypatch):
        """对话式分支应传 build_chat_system_prompt + plan_first=False + final_as_payload=False。"""
        from competitor_agent.agent.prompts.react_system import build_chat_system_prompt
        from competitor_agent.facade import api as api_mod

        seen: dict[str, object] = {}
        orig = api_mod.CompetitorAnalysisAPI._react_loop

        def _spy(self, task, session_id, **kwargs):
            seen["system_prompt"] = kwargs.get("system_prompt")
            seen["plan_first"] = kwargs.get("plan_first")
            seen["final_as_payload"] = kwargs.get("final_as_payload")
            return orig(self, task, session_id, **kwargs)

        monkeypatch.setattr(api_mod.CompetitorAnalysisAPI, "_react_loop", _spy)
        result = _chat_api().run("普通问题")
        assert isinstance(result, ChatResult)
        assert seen["system_prompt"] == build_chat_system_prompt()
        assert seen["plan_first"] is False
        assert seen["final_as_payload"] is False


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

            def run(self, task: str, *, session_id: str | None = None) -> CompetitorReport:
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
