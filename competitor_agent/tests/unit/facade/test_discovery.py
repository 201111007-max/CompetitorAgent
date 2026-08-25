"""facade/api.py 设计文档 20：N 向 compare + discover（市场普查/发现）"""
import pytest
from competitor_agent.core.competitor_registry import COMPETITOR_REGISTRY
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.report import ComparisonReport
from competitor_agent.facade.api import CompetitorAnalysisAPI


class FakeExtractor:
    def fetch(self, gap, context):
        from competitor_agent.domain_types import Observation, SourceEvidence

        url = str(context.kwargs.get("url"))
        if "pricing" in url:
            text = "Pro $20/month\nTeams $40/month\nUltra $60/month"
        elif "docs" in url:
            text = "supports MCP integration and agent mode."
        else:
            text = "is an AI code editor."
        ev = SourceEvidence(source_name="web_extractor", url=url, content_hash=str(hash(url)), trust_level=0.9)
        return Observation(gap_field=gap.field, source="web_extractor", raw_text=text, evidence=ev)


def _api(mock_llm, web_tool=None, **kwargs):
    return CompetitorAnalysisAPI(
        extractor=FakeExtractor(), llm=mock_llm, use_llm=True, web_tool=web_tool, **kwargs
    )


def _two_candidate_web_tool(task: str) -> list[dict]:
    return [
        {"name": "cursor", "home": "https://www.cursor.com", "pricing": "https://www.cursor.com/pricing"},
        {"name": "windsurf", "home": "https://windsurf.com", "pricing": "https://windsurf.com/pricing"},
    ]


class TestCompareNway:
    def test_compare_three(self, mock_llm):
        if "windsurf" not in COMPETITOR_REGISTRY:
            COMPETITOR_REGISTRY["windsurf"] = Competitor(name="windsurf", aliases=["windsurf ai"])
        api = _api(mock_llm)
        result = api.compare("Cursor", "Windsurf", "Copilot")
        assert isinstance(result, ComparisonReport)
        assert len(result.reports) == 3
        md = result.markdown_report
        assert "cursor" in md and "windsurf" in md and "copilot" in md
        assert "品类格局矩阵" in md

    def test_compare_combined_task_nway(self, mock_llm):
        api = _api(mock_llm)
        result = api.compare("对比 Cursor 和 Windsurf 和 Copilot")
        assert len(result.reports) >= 2

    def test_compare_two_still_works(self, mock_llm):
        api = _api(mock_llm)
        result = api.compare("Cursor", "Windsurf")
        assert len(result.reports) == 2
        assert "vs" in result.markdown_report

    def test_compare_single_raises(self, mock_llm):
        api = _api(mock_llm)
        try:
            api.compare("Cursor")
        except ValueError:
            assert True
        else:
            assert False, "单竞品应抛 ValueError"


class TestDiscover:
    def test_discover_uses_web_tool_and_produces_report(self, mock_llm):
        api = _api(mock_llm, web_tool=_two_candidate_web_tool)
        result = api.discover("帮我寻找市场上所有 AI coding agent")
        assert isinstance(result, ComparisonReport)
        assert len(result.reports) >= 2
        # 不再产出假竞品 ai-coding-agent，也不 0 维度
        md = result.markdown_report
        assert "ai-coding-agent" not in md
        assert "品类格局矩阵" in md

    def test_discover_without_web_tool_graceful(self, mock_llm):
        """设计文档 62 §3.5：无 web_tool → 候选枚举返回可读回灌，Lead 优雅收尾（空矩阵 + 结论），不报错。"""
        api = _api(mock_llm)
        result = api.discover("市场上所有 AI coding agent")
        assert isinstance(result, ComparisonReport)
        assert "未发现候选竞品" in result.markdown_report

    def test_discover_emits_discovery_event(self, mock_llm):
        events = []
        api = CompetitorAnalysisAPI(
            extractor=FakeExtractor(),
            llm=mock_llm,
            use_llm=True,
            event_sink=events.append,
            web_tool=_two_candidate_web_tool,
        )
        api.discover("市场上所有 AI coding agent")
        assert any(e.event == "discovery" for e in events)
        assert any(e.payload and e.payload.get("candidates") for e in events)

    def test_discover_emits_per_candidate_events_before_discovery(self, mock_llm):
        """discovery 阶段逐候选实时推送（discovery.candidate），先于聚合的 discovery 事件。"""

        def web_tool(task: str) -> list[dict]:
            return [
                {"name": "cursor", "home": "https://www.cursor.com"},
                {"name": "windsurf", "home": "https://windsurf.com"},
            ]

        events = []
        api = CompetitorAnalysisAPI(
            extractor=FakeExtractor(),
            llm=mock_llm,
            use_llm=True,
            event_sink=events.append,
            web_tool=web_tool,
        )
        api.discover("帮我寻找市场上所有 AI coding agent")
        cands = [e.payload["candidate"] for e in events if e.event == "discovery.candidate" and e.payload]
        assert cands == ["cursor", "windsurf"], f"应逐候选推送，实际: {cands}"
        seq = [e.event for e in events]
        assert seq.index("discovery.candidate") < seq.index("discovery")

    def test_task_with_sources_injects_links(self, mock_llm):
        api = _api(mock_llm)
        competitor = Competitor(
            name="ghost-agent",
            official_links={"home": "https://ghost.dev", "pricing": "https://ghost.dev/pricing"},
        )
        task = api._task_with_sources(competitor)
        assert "ghost-agent" in task
        assert "https://ghost.dev" in task
