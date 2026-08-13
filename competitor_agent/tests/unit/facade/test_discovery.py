"""facade/api.py 设计文档 20：N 向 compare + discover（市场普查/发现）"""
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


def _api(web_tool=None, **kwargs):
    return CompetitorAnalysisAPI(extractor=FakeExtractor(), use_llm=False, web_tool=web_tool, **kwargs)


class TestCompareNway:
    def test_compare_three(self):
        if "windsurf" not in COMPETITOR_REGISTRY:
            COMPETITOR_REGISTRY["windsurf"] = Competitor(name="windsurf", aliases=["windsurf ai"])
        api = _api()
        result = api.compare("Cursor", "Windsurf", "Copilot")
        assert isinstance(result, ComparisonReport)
        assert len(result.reports) == 3
        md = result.markdown_report
        assert "cursor" in md and "windsurf" in md and "copilot" in md
        assert "品类格局矩阵" in md

    def test_compare_combined_task_nway(self):
        api = _api()
        result = api.compare("对比 Cursor 和 Windsurf 和 Copilot")
        assert len(result.reports) >= 2

    def test_compare_two_still_works(self):
        api = _api()
        result = api.compare("Cursor", "Windsurf")
        assert len(result.reports) == 2
        assert "vs" in result.markdown_report

    def test_compare_single_raises(self):
        api = _api()
        try:
            api.compare("Cursor")
        except ValueError:
            assert True
        else:
            assert False, "单竞品应抛 ValueError"


class TestDiscover:
    def test_discover_uses_web_tool_and_produces_report(self):
        def web_tool(task: str) -> list[dict]:
            return [
                {"name": "cursor", "home": "https://www.cursor.com", "pricing": "https://www.cursor.com/pricing"},
                {"name": "windsurf", "home": "https://windsurf.com", "pricing": "https://windsurf.com/pricing"},
            ]

        api = _api(web_tool=web_tool)
        result = api.discover("帮我寻找市场上所有 AI coding agent")
        assert isinstance(result, ComparisonReport)
        assert len(result.reports) >= 2
        # 不再产出假竞品 ai-coding-agent，也不 0 维度
        md = result.markdown_report
        assert "ai-coding-agent" not in md
        assert "品类格局矩阵" in md

    def test_discover_fallback_no_web_tool(self):
        """无 web_tool：内置兜底清单，至少产出 ≥2 报告且带矩阵。"""
        api = _api()
        result = api.discover("市场上所有 AI coding agent")
        assert len(result.reports) >= 2
        assert "品类格局矩阵" in result.markdown_report

    def test_discover_emits_discovery_event(self):
        events = []
        api = CompetitorAnalysisAPI(extractor=FakeExtractor(), use_llm=False, event_sink=events.append)
        api.discover("市场上所有 AI coding agent")
        assert any(e.event == "discovery" for e in events)
        assert any(e.payload and e.payload.get("candidates") for e in events)

    def test_discover_emits_per_candidate_events_before_discovery(self):
        """discovery 阶段逐候选实时推送（discovery.candidate），先于聚合的 discovery 事件。"""

        def web_tool(task: str) -> list[dict]:
            return [
                {"name": "cursor", "home": "https://www.cursor.com"},
                {"name": "windsurf", "home": "https://windsurf.com"},
            ]

        events = []
        api = CompetitorAnalysisAPI(
            extractor=FakeExtractor(), use_llm=False, event_sink=events.append, web_tool=web_tool
        )
        api.discover("帮我寻找市场上所有 AI coding agent")
        cands = [e.payload["candidate"] for e in events if e.event == "discovery.candidate" and e.payload]
        assert cands == ["cursor", "windsurf"], f"应逐候选推送，实际: {cands}"
        seq = [e.event for e in events]
        assert seq.index("discovery.candidate") < seq.index("discovery")

    def test_task_with_sources_injects_links(self):
        api = _api()
        competitor = Competitor(
            name="ghost-agent",
            official_links={"home": "https://ghost.dev", "pricing": "https://ghost.dev/pricing"},
        )
        task = api._task_with_sources(competitor)
        assert "ghost-agent" in task
        assert "https://ghost.dev" in task
