"""设计文档 96 — 对话环入口 run_conversation()：chat-first + generate_report 工具化。

取代 test_chat_gate_64.py 的意图门控测试（doc 64 §5 CHAT 门控随 parse_task 退役）：
① 闲聊/普通提问 → 环内 prose 回答，零 generate_report 触发（应触发未触发反向用例）；
② 分析类请求 → Lead 自调 generate_report → ChatResult.report 挂产物（报告面板据此渲染）；
③ 对话环工具面两段式（仅 web_search + kb_recall + generate_report，无报告流水线工具）；
④ generate_report 触发时发 phase_start(phase="report_tool") 活动事件（代价 #5）。
"""
from __future__ import annotations

from competitor_agent.domain_types.report import (
    ChatResult,
    ComparisonReport,
    CompetitorReport,
)
from competitor_agent.facade.api import CompetitorAnalysisAPI


class FakeExtractor:
    def fetch(self, gap, context):
        from competitor_agent.domain_types import Observation, SourceEvidence

        url = str(context.kwargs.get("url"))
        text = "Pro $20/month" if "pricing" in url else "is an AI code editor."
        ev = SourceEvidence(source_name="web_extractor", url=url, content_hash=str(hash(url)), trust_level=0.9)
        return Observation(gap_field=str(getattr(gap, "field", "")), source="web_extractor", raw_text=text, evidence=ev)


def _api(mock_llm, **kwargs) -> CompetitorAnalysisAPI:
    return CompetitorAnalysisAPI(
        extractor=FakeExtractor(), llm=mock_llm, use_llm=True, **kwargs
    )


class TestConversationEntry:
    def test_chat_task_returns_chatresult_without_report(self, mock_llm):
        """闲聊 → 环内 prose 回答，零 generate_report 触发。"""
        result = _api(mock_llm).run_conversation("今天天气怎么样")
        assert isinstance(result, ChatResult)
        assert result.report is None
        assert result.answer
        assert result.terminal_state == "success"

    def test_analysis_task_triggers_generate_report(self, mock_llm):
        """分析请求 → generate_report → ChatResult.report 挂 CompetitorReport。"""
        result = _api(mock_llm).run_conversation("分析 Cursor")
        assert isinstance(result, ChatResult)
        assert isinstance(result.report, CompetitorReport)
        assert result.report.competitor.name == "cursor"
        assert result.answer  # 报告摘要回灌后的 prose 收尾

    def test_compare_task_triggers_comparison_report(self, mock_llm):
        result = _api(mock_llm).run_conversation("对比 Cursor 和 Windsurf")
        assert isinstance(result, ChatResult)
        assert isinstance(result.report, ComparisonReport)

    def test_report_session_id_matches_conversation(self, mock_llm):
        """generate_report 子流程复用对话 sid（级联取消/共享预算/同一 session log）。"""
        result = _api(mock_llm).run_conversation("分析 Cursor", session_id="sess_conv96")
        assert result.session_id == "sess_conv96"
        assert result.report is not None

    def test_chat_task_emits_no_report_event(self, mock_llm):
        events = []
        result = _api(mock_llm, event_sink=events.append).run_conversation("你好")
        assert isinstance(result, ChatResult)
        assert result.report is None
        assert not any(e.event == "report" for e in events)

    def test_analysis_task_emits_report_tool_activity_event(self, mock_llm):
        """generate_report 入口发 phase_start(report_tool) 活动事件（代价 #5 收集期零反馈治理）。"""
        events = []
        result = _api(mock_llm, event_sink=events.append).run_conversation("分析 Cursor")
        assert result.report is not None
        assert any(
            e.event == "phase_start" and e.phase == "report_tool" for e in events
        )
        assert any(e.event == "report" for e in events)  # 报告面板事件照常透传

    def test_conversation_loop_is_two_phase_tool_surface(self, mock_llm, monkeypatch):
        """对话环工具面 = {web_search, kb_recall, generate_report}（无 make_plan/delegate）。"""
        from competitor_agent.facade import analysis_service as analysis_mod

        seen: dict[str, object] = {}
        orig = analysis_mod.build_react_dispatcher

        def _spy(**kwargs):
            dispatcher = orig(**kwargs)
            if kwargs.get("only") == ("web_search",):
                # 只记录对话环那次调用（generate_report 子 loop 是全量工具面）
                seen["specs"] = set(dispatcher.specs)
            return dispatcher

        monkeypatch.setattr(analysis_mod, "build_react_dispatcher", _spy)
        result = _api(mock_llm).run_conversation("分析 Cursor")
        assert result.report is not None
        assert seen["specs"] == {"web_search", "kb_recall", "generate_report"}

    def test_run_conversation_system_prompt_is_chat_prompt(self, mock_llm, monkeypatch):
        from competitor_agent.agent.prompts.react_system import build_chat_system_prompt
        from competitor_agent.facade import analysis_service as analysis_mod

        seen: dict[str, object] = {}
        orig = analysis_mod.AnalysisService._conversation_loop

        def _spy(self, task, sid, history_messages, captured):
            loop = orig(self, task, sid, history_messages, captured)
            seen["system_prompt"] = loop._system_prompt_override
            seen["plan_first"] = loop._plan_first
            seen["final_as_payload"] = loop._final_as_payload
            return loop

        monkeypatch.setattr(analysis_mod.AnalysisService, "_conversation_loop", _spy)
        result = _api(mock_llm).run_conversation("分析 Cursor")
        assert result.report is not None
        assert seen["system_prompt"] == build_chat_system_prompt()
        assert seen["plan_first"] is False
        assert seen["final_as_payload"] is False
