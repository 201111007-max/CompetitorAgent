"""设计文档 62 M3 — 统一 run() 入口分派单测。

覆盖：run() 按 resolution 语义路由（DISCOVERY→discover 语义 / COMPARE→N 向对比 /
单竞品→analyze）；session_id 透传；discover()/compare() 兼容薄包装（deprecated 告警）。
"""
from __future__ import annotations

import logging

from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.report import ComparisonReport, CompetitorReport
from competitor_agent.facade.api import CompetitorAnalysisAPI


class FakeExtractor:
    def fetch(self, gap, context):
        from competitor_agent.domain_types import Observation, SourceEvidence

        url = str(context.kwargs.get("url"))
        if "pricing" in url:
            text = "Pro $20/month\nTeams $40/month"
        else:
            text = "is an AI code editor."
        ev = SourceEvidence(source_name="web_extractor", url=url, content_hash=str(hash(url)), trust_level=0.9)
        return Observation(gap_field=gap.field, source="web_extractor", raw_text=text, evidence=ev)


def _api(mock_llm, web_tool=None, **kwargs) -> CompetitorAnalysisAPI:
    return CompetitorAnalysisAPI(
        extractor=FakeExtractor(), llm=mock_llm, use_llm=True, web_tool=web_tool, **kwargs
    )


def _two_candidate_web_tool(task: str) -> list[dict]:
    return [
        {"name": "cursor", "home": "https://www.cursor.com", "pricing": "https://www.cursor.com/pricing"},
        {"name": "windsurf", "home": "https://windsurf.com", "pricing": "https://windsurf.com/pricing"},
    ]


class TestRunRouting:
    def test_run_single_routes_to_analyze(self, mock_llm):
        api = _api(mock_llm)
        report = api.run("分析 Cursor")
        assert isinstance(report, CompetitorReport)
        assert report.competitor.name == "cursor"

    def test_run_compare_routes_to_compare(self, mock_llm):
        api = _api(mock_llm)
        report = api.run("对比 Cursor 和 Windsurf")
        assert isinstance(report, ComparisonReport)
        assert [r.competitor.name for r in report.reports] == ["cursor", "windsurf"]

    def test_run_discovery_routes_to_discovery(self, mock_llm):
        api = _api(mock_llm, web_tool=_two_candidate_web_tool)
        report = api.run("帮我找市场上所有 coding agent")
        assert isinstance(report, ComparisonReport)
        assert "品类格局矩阵" in report.markdown_report

    def test_run_propagates_session_id(self, mock_llm, monkeypatch):
        api = _api(mock_llm)
        seen: dict[str, object] = {}
        api._run_compare = lambda names, session_id=None: seen.update(sid=session_id) or ComparisonReport(
            competitors=[Competitor("a"), Competitor("b")], reports=[], markdown_report="x"
        )
        api.run("对比 Cursor 和 Windsurf", session_id="sess_abc")
        assert seen["sid"] == "sess_abc"


class TestCompatWrappers:
    def test_compare_wrapper_deprecation_warns(self, mock_llm, caplog):
        api = _api(mock_llm)
        with caplog.at_level(logging.WARNING, logger="competitor_agent"):
            api.compare("Cursor", "Windsurf")
        assert any("compare() 已废弃" in r.getMessage() for r in caplog.records)

    def test_discover_wrapper_deprecation_warns(self, mock_llm, caplog):
        api = _api(mock_llm, web_tool=_two_candidate_web_tool)
        with caplog.at_level(logging.WARNING, logger="competitor_agent"):
            api.discover("帮我找所有 coding agent")
        assert any("discover() 已废弃" in r.getMessage() for r in caplog.records)

    def test_compare_wrapper_still_works(self, mock_llm):
        api = _api(mock_llm)
        result = api.compare("Cursor", "Windsurf")
        assert isinstance(result, ComparisonReport)
        assert len(result.reports) == 2
