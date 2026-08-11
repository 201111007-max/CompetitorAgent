"""集成测试 — analyze_team() 多 Agent 流水线真实协作

对齐设计文档 11 §3.1：CollectorAgent→AnalyzerAgent→ValidatorAgent→ReporterAgent
事件驱动 + 状态决策（SUCCESS/RETRY/DEGRADED/FAILED）产出完整报告。
"""

from __future__ import annotations

import pytest

from competitor_agent.facade.api import CompetitorAnalysisAPI

pytestmark = pytest.mark.integration


class TestTeamFlow:
    def test_analyze_team_produces_complete_report(self, fake_extractor) -> None:
        api = CompetitorAnalysisAPI(extractor=fake_extractor, use_llm=False)
        report = api.analyze_team("分析 Cursor")

        assert report.dimension_results
        assert report.terminal_state == "success"
        assert report.overall_confidence > 0
        assert "# cursor 竞品分析报告" in report.markdown_report
        assert "## 维度结论" in report.markdown_report

    def test_team_evidence_carries_source_url(self, fake_extractor) -> None:
        api = CompetitorAnalysisAPI(extractor=fake_extractor, use_llm=False)
        report = api.analyze_team("分析 Cursor", max_retries=1)

        for result in report.dimension_results:
            assert result.evidence, "多 Agent 结论应携带证据链"
            assert all(ev.url and ev.url.startswith("https://") for ev in result.evidence)

    def test_team_memory_sediments_skills(self, fake_extractor, memory) -> None:
        api = CompetitorAnalysisAPI(extractor=fake_extractor, use_llm=False, memory=memory)
        api.analyze_team("分析 Cursor")

        assert memory.retrieve_skills("cursor"), "多 Agent 路径成功后应沉淀技能"
        assert memory.source_success_rates(), "多 Agent 路径应记录数据源成功率"
