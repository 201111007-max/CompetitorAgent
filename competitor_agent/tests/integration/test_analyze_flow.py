"""集成测试 — analyze() 完整链路（规划→采集→分析→报告）真实协作

单 Agent（mode="single"）与多 Agent（mode="team"）两条主流程：
- 报告结构完整（竞品名 / 维度结论 / 综合置信度 / Markdown）
- 证据链带 source_url（采集→证据→报告闭环）
- 报告可被 benchmark 的 extract_prediction 评测（复用设计文档 03）
"""

from __future__ import annotations

import pytest

from competitor_agent.config.loader import AppConfig, CollectorConfig
from competitor_agent.evaluation.benchmark import extract_prediction
from competitor_agent.facade.api import CompetitorAnalysisAPI

pytestmark = pytest.mark.integration

# 离线环境 URL 守卫（DNS 解析）会拦截 before 采集器运行：关闭守卫让采集器真被命中
_OFFLINE_CFG = AppConfig(collector=CollectorConfig(block_private_urls=False))


class TestAnalyzeFlow:
    def test_single_mode_full_chain_produces_report(self, fake_extractor, mock_llm) -> None:
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor, llm=mock_llm, use_llm=True, max_iterations=10, config=_OFFLINE_CFG
        )
        report = api.analyze("分析 Cursor", mode="single")

        assert report.competitor.name == "cursor"
        assert report.dimension_results
        assert report.overall_confidence > 0
        assert "# cursor 竞品分析报告" in report.markdown_report
        assert "## 维度结论" in report.markdown_report
        assert "### " in report.markdown_report

    def test_single_flow_evidence_carries_source_url(self, fake_extractor, mock_llm) -> None:
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor, llm=mock_llm, use_llm=True, max_iterations=10, config=_OFFLINE_CFG
        )
        report = api.analyze("只分析 cursor 的定价", mode="single")

        pricing = [r for r in report.dimension_results if r.dimension == "pricing"]
        assert pricing, "定价维度应被采集并分析"
        assert pricing[0].evidence, "维度结论应携带证据链"
        assert all(ev.url for ev in pricing[0].evidence), "证据应带 source_url"

    def test_single_flow_markdown_lists_evidence(self, fake_extractor, mock_llm) -> None:
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor, llm=mock_llm, use_llm=True, max_iterations=10, config=_OFFLINE_CFG
        )
        report = api.analyze("只分析 cursor 的定价", mode="single")

        assert "证据:" in report.markdown_report
        # doc 49：源选择由 Lead/子 Agent 的 URL 决定（删除 source_selector 官方源路由）；
        # mock 抓 example.com 假源，断言证据 URL 存在且非空（采集→证据→报告闭环）
        urls = [ev.url for r in report.dimension_results if r.dimension == "pricing" for ev in r.evidence]
        assert urls and all(urls), "定价维度证据应带非空 source_url"

    def test_team_mode_full_chain_produces_report(self, fake_extractor, mock_llm) -> None:
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor, llm=mock_llm, use_llm=True, config=_OFFLINE_CFG
        )
        report = api.analyze("分析 Cursor")  # 默认 team 多 Agent 流水线

        assert report.dimension_results
        assert report.terminal_state == "success"
        assert "# cursor 竞品分析报告" in report.markdown_report

    def test_events_flow_from_plan_to_report(self, fake_extractor, mock_llm) -> None:
        events: list = []

        def sink(event: object) -> None:
            events.append(event)

        api = CompetitorAnalysisAPI(
            extractor=fake_extractor, llm=mock_llm, use_llm=True, event_sink=sink, max_iterations=10,
            config=_OFFLINE_CFG,
        )
        api.analyze("分析 Cursor", mode="single")

        assert events
        assert any(e.event == "phase_start" for e in events)
        assert any(e.event == "report" for e in events)

    def test_real_report_is_benchmark_evaluable(self, fake_extractor, mock_llm) -> None:
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor, llm=mock_llm, use_llm=True, max_iterations=10, config=_OFFLINE_CFG
        )
        report = api.analyze("只分析 cursor 的定价", mode="single")

        # 复用设计文档 03 的字段抽取：真实报告同命名空间可评测
        prediction = extract_prediction(report, "pricing", {"pro": "$20/month", "teams": "$40/month"})
        assert prediction.get("pro") == "$20/month"
        assert prediction.get("teams") == "$40/month"
