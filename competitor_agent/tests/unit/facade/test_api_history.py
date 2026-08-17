"""facade/api.py M5 增强单测：会话历史 / compare / continue_analysis"""
import pytest

from competitor_agent.domain_types.report import ComparisonReport
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.interfaces.context import ChatMessage

CURSOR_PRICING = "Pro $20/month\nTeams $40/month\nUltra $60/month"


class FakeExtractor:
    def fetch(self, gap, context):
        from competitor_agent.domain_types import Observation, SourceEvidence

        url = str(context.kwargs.get("url"))
        if "pricing" in url:
            text = CURSOR_PRICING
        elif "docs" in url:
            text = "Cursor supports MCP integration and agent mode."
        else:
            text = "Cursor is an AI code editor."
        ev = SourceEvidence(source_name="web_extractor", url=url, content_hash=str(hash(url)), trust_level=0.9)
        return Observation(gap_field=gap.field, source="web_extractor", raw_text=text, evidence=ev)


def _api(mock_llm, **kwargs):
    return CompetitorAnalysisAPI(extractor=FakeExtractor(), llm=mock_llm, use_llm=True, **kwargs)


class TestHistoryContext:
    def test_history_prev_message_used_for_disambiguation(self, mock_llm):
        api = _api(mock_llm)
        report = api.analyze("分析 Cursor")
        assert report.competitor.name == "cursor"
        history = [
            ChatMessage(role="user", content="分析 Cursor"),
            ChatMessage(role="assistant", content=f"# cursor 竞品分析报告\n{report.markdown_report}"),
        ]
        # 相对指代（无明确竞品），从历史承接 Cursor
        second = api.analyze("那定价呢", conversation_history=history)
        assert second.competitor.name == "cursor"

    def test_no_history_keeps_unknown(self, mock_llm):
        """无历史时相对指代解析为 unknown；规划无法定竞品 → 报错（LLM 时代无规则兜底）。"""
        from competitor_agent.core.task_parser import parse_task

        parsed = parse_task("那定价呢", llm=mock_llm, use_llm=True)
        assert parsed.primary_competitor == "unknown"
        api = _api(mock_llm)
        with pytest.raises(ValueError):
            api.analyze("那定价呢")

    def test_history_emits_context(self, mock_llm):
        events = []
        api = CompetitorAnalysisAPI(
            extractor=FakeExtractor(), llm=mock_llm, use_llm=True, event_sink=events.append
        )
        api.analyze("分析 Cursor")
        api.analyze("那性能呢", conversation_history=[ChatMessage(role="user", content="分析 Cursor")])
        assert any(e.message.startswith("规划:") for e in events)


class TestCompare:
    def test_compare_explicit(self, mock_llm):
        from competitor_agent.core.competitor_registry import COMPETITOR_REGISTRY

        if "windsurf" not in COMPETITOR_REGISTRY:
            import competitor_agent.core.competitor_registry as cr
            from competitor_agent.domain_types.competitor import Competitor

            cr.COMPETITOR_REGISTRY["windsurf"] = Competitor(name="windsurf", aliases=["windsurf ai"])
        api = _api(mock_llm)
        result = api.compare("Cursor", "Windsurf")
        assert isinstance(result, ComparisonReport)
        assert len(result.reports) == 2
        assert "vs" in result.markdown_report

    def test_compare_from_combined_task(self, mock_llm):
        api = _api(mock_llm)
        result = api.compare("对比 Cursor 和 Windsurf")
        assert len(result.reports) == 2

    def test_compare_single_arg_raises(self, mock_llm):
        api = _api(mock_llm)
        try:
            api.compare("Cursor")
        except ValueError:
            assert True
        else:
            assert False, "单竞品应抛 ValueError"


class TestContinueAnalysis:
    def test_continue_analysis_no_checkpoint_raises(self, tmp_path, mock_llm):
        api = _api(mock_llm)
        try:
            api.continue_analysis("sess_nonexistent")
        except ValueError:
            assert True
        else:
            assert False, "无 checkpoint 应抛 ValueError"