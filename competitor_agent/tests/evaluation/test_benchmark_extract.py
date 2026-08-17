"""benchmark 真实执行单元测试（benchmark_design.md §5）

- extract_prediction：从已知真实报告按维度抽取可比对字段
- BenchmarkMockLLM：确定性抽取（plans / features / benchmarks / 规划解析回退）
- extract_strategy / real_trace：真实证据反推选源、成本与闭环
"""
import json

from competitor_agent.domain_types.report import CompetitorReport, DimensionResult
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.observation import SourceEvidence
from competitor_agent.evaluation.benchmark import (
    BenchmarkExtractor,
    BenchmarkMockLLM,
    extract_prediction,
    extract_strategy,
    real_trace,
)


def _report_with(dimension: str, details: dict) -> CompetitorReport:
    result = DimensionResult(
        dimension=dimension,
        summary="summary",
        details=details,
        confidence=0.8,
        evidence=[SourceEvidence(source_name="web_extractor", url="https://x.com/page")],
    )
    return CompetitorReport(competitor=Competitor(name="cursor"), dimension_results=[result])


class TestExtractPrediction:
    def test_pricing_plan_price(self):
        report = _report_with("pricing", {"plans": [{"name": "Pro", "price": "20", "period": "month"}]})
        pred = extract_prediction(report, "pricing", {"pro": "$20/month", "team": "$40/month"})
        assert pred == {"pro": "$20/month", "team": ""}

    def test_pricing_missing_plan_returns_empty(self):
        report = _report_with("pricing", {"plans": [{"name": "pro", "price": "20", "period": "month"}]})
        pred = extract_prediction(report, "pricing", {"enterprise": ""})
        assert pred == {"enterprise": ""}

    def test_feature_present_flag(self):
        report = _report_with("feature", {"features": ["supports mcp and cli"]})
        pred = extract_prediction(report, "feature", {"mcp": "true", "cli": "true", "rag": "false"})
        assert pred == {"mcp": "true", "cli": "true", "rag": "false"}

    def test_benchmark_score_from_mock_shape(self):
        report = _report_with("performance", {"benchmarks": [{"name": "latency", "score": "200.5ms"}]})
        pred = extract_prediction(report, "performance", {"latency": "200.5ms", "aider": ""})
        assert pred == {"latency": "200.5ms", "aider": ""}

    def test_benchmark_score_from_rule_shape(self):
        # 规则层 details 形如 {"raw": "Latency: 300ms"}
        report = _report_with("performance", {"benchmarks": [{"raw": "Latency: 300ms"}]})
        pred = extract_prediction(report, "performance", {"latency": "300ms"})
        assert pred == {"latency": "300ms"}

    def test_missing_dimension_returns_empty_fields(self):
        report = CompetitorReport(competitor=Competitor(name="x"), dimension_results=[])
        pred = extract_prediction(report, "pricing", {"pro": "$20/month"})
        assert pred == {"pro": ""}


class TestExtractNewDimensions:
    """设计文档 29：生态 / 口碑 / 时间线新维度字段抽取"""

    def test_ecosystem_mcp_count_and_ide(self):
        report = _report_with("ecosystem", {"mcp_servers": [{"name": "a"}, {"name": "b"}], "ide_support": ["vscode", "jetbrains"]})
        pred = extract_prediction(report, "ecosystem", {"mcp_servers": 2, "vscode": "true", "jetbrains": "true"})
        assert pred == {"mcp_servers": 2, "vscode": "true", "jetbrains": "true"}

    def test_ecosystem_plugin_count(self):
        report = _report_with("ecosystem", {"plugins": {"count": 3, "rating": 4.8, "top": ["a", "b", "c"]}})
        pred = extract_prediction(report, "ecosystem", {"plugins": 3})
        assert pred == {"plugins": 3}

    def test_ecosystem_empty_payload_no_fabrication(self):
        report = _report_with("ecosystem", {"mcp_servers": [], "ide_support": []})
        pred = extract_prediction(report, "ecosystem", {"mcp_servers": 0, "vscode": "false"})
        assert pred == {"mcp_servers": 0, "vscode": "false"}

    def test_sentiment_positive_polarity(self):
        report = _report_with("sentiment", {"polarity_ratio": {"pos": 1.0, "neg": 0.0, "neu": 0.0}})
        pred = extract_prediction(report, "sentiment", {"polarity": "pos", "positive": "true"})
        assert pred == {"polarity": "pos", "positive": "true"}

    def test_sentiment_negative_polarity(self):
        report = _report_with("sentiment", {"polarity_ratio": {"pos": 0.0, "neg": 0.8, "neu": 0.2}})
        pred = extract_prediction(report, "sentiment", {"polarity": "neg", "negative": "true"})
        assert pred == {"polarity": "neg", "negative": "true"}

    def test_sentiment_mixed_neutral_polarity(self):
        report = _report_with("sentiment", {"polarity_ratio": {"pos": 0.5, "neg": 0.5, "neu": 0.0}})
        pred = extract_prediction(report, "sentiment", {"polarity": "neu", "positive": "true", "negative": "true"})
        assert pred == {"polarity": "neu", "positive": "true", "negative": "true"}

    def test_sentiment_empty_payload_no_fabrication(self):
        report = _report_with("sentiment", {"polarity_ratio": {"pos": 0.0, "neg": 0.0, "neu": 0.0}})
        pred = extract_prediction(report, "sentiment", {"polarity": "neu", "positive": "false", "negative": "false"})
        assert pred == {"polarity": "neu", "positive": "false", "negative": "false"}

    def test_timeline_no_events_on_first_run(self):
        report = _report_with("pricing", {"plans": []})
        report.markdown_report = "# cursor\n\n## 定价\n...no timeline section"
        pred = extract_prediction(report, "roadmap", {"has_events": "false"})
        assert pred == {"has_events": "false"}

    def test_timeline_events_when_section_present(self):
        report = _report_with("pricing", {"plans": []})
        report.markdown_report = "# cursor\n\n## 竞品时间线\n| 日期 | 类型 | 变化 | 证据 |"
        pred = extract_prediction(report, "roadmap", {"has_events": "true"})
        assert pred == {"has_events": "true"}


class TestBenchmarkMockLLM:
    def test_pricing_plans_parsed(self):
        out = json.loads(BenchmarkMockLLM().complete([
            {"role": "system", "content": "竞品定价分析师…提取定价计划…"},
            {"role": "user", "content": "Pro $20/month\nTeam $40/month"},
        ]))
        assert out["details"]["plans"] == [
            {"name": "pro", "price": "20", "period": "month"},
            {"name": "team", "price": "40", "period": "month"},
        ]

    def test_feature_markers_collected(self):
        out = json.loads(BenchmarkMockLLM().complete([
            {"role": "system", "content": "竞品功能分析师…核心功能列表…"},
            {"role": "user", "content": "Supports MCP and CLI."},
        ]))
        assert any("mcp" in f.lower() for f in out["details"]["features"])

    def test_benchmarks_from_colon_lines(self):
        out = json.loads(BenchmarkMockLLM().complete([
            {"role": "system", "content": "性能分析师…基准测试数据…"},
            {"role": "user", "content": "Latency: 250ms\nSWE-bench: 68%"},
        ]))
        by_name = {b["name"]: b["score"] for b in out["details"]["benchmarks"]}
        assert by_name == {"latency": "250ms", "swe-bench": "68%"}

    def test_rag_suffix_stripped(self):
        out = json.loads(BenchmarkMockLLM().complete([
            {"role": "system", "content": "竞品定价分析师…提取定价计划…"},
            {"role": "user", "content": "Pro $20/month\n[知识库参考片段（外部事实依据，可引用其来源）]\n- [cursor/pricing] fake ctx"},
        ]))
        assert out["details"]["plans"][0]["price"] == "20"

    def test_parse_prompt_infers_competitor_from_task(self):
        # 设计文档 47：解析 mock 即固定 oracle——从任务文本推断竞品/分辨率（不再有规则回退）
        out = json.loads(BenchmarkMockLLM().complete([
            {"role": "system", "content": "你是竞品分析任务的语义解析器…"},
            {"role": "user", "content": "分析 cursor 定价"},
        ]))
        assert out["competitors"] == ["cursor"]
        assert out["dimensions"] is None
        assert out["resolution"] == "registry"

    def test_ecosystem_signals_collected(self):
        out = json.loads(BenchmarkMockLLM().complete([
            {"role": "system", "content": "你是竞品生态分析师…盘点生态能力…"},
            {"role": "user", "content": "MCP server: GitHub integration\nMCP server: Slack integration\nSupports VSCode and JetBrains IDE plugins."},
        ]))
        details = out["details"]
        assert len(details["mcp_servers"]) == 2
        assert "vscode" in details["ide_support"]
        assert "jetbrains" in details["ide_support"]

    def test_sentiment_polarity_parsed(self):
        out = json.loads(BenchmarkMockLLM().complete([
            {"role": "system", "content": "你是竞品社区口碑分析师…提取口碑信号…"},
            {"role": "user", "content": "Some love the integration.\nOthers think it is bad."},
        ]))
        assert out["details"]["polarity_ratio"] == {"pos": 0.5, "neg": 0.5, "neu": 0.0}

    def test_sentiment_empty_low_confidence(self):
        out = json.loads(BenchmarkMockLLM().complete([
            {"role": "system", "content": "你是竞品社区口碑分析师…提取口碑信号…"},
            {"role": "user", "content": "The product ships regular updates."},
        ]))
        assert out["details"]["polarity_ratio"] == {"pos": 0.0, "neg": 0.0, "neu": 0.0}
        assert out["confidence"] < 0.5


class TestExtractStrategy:
    def test_evidence_urls_dedup_ordered(self):
        report = CompetitorReport(
            competitor=Competitor(name="cursor"),
            dimension_results=[
                DimensionResult(
                    dimension="pricing",
                    evidence=[
                        SourceEvidence(source_name="web_extractor", url="https://a.com"),
                        SourceEvidence(source_name="web_extractor", url="https://a.com"),
                    ],
                ),
                DimensionResult(
                    dimension="feature",
                    evidence=[SourceEvidence(source_name="web_extractor", url="https://b.com")],
                ),
            ],
        )
        urls, cost, complete = extract_strategy(report, best_url="https://a.com", fail_urls=["https://a.com"])
        assert urls == ["https://a.com", "https://b.com"]
        assert cost == 0.03  # 2 成功 + 1 失败首候选源
        assert complete is True
        assert "https://a.com" in urls  # best 命中

    def test_no_evidence_incomplete(self):
        report = CompetitorReport(competitor=Competitor(name="x"), dimension_results=[])
        urls, cost, complete = extract_strategy(report, best_url="https://nope.com")
        assert urls == []
        assert complete is False

    def test_real_trace_from_evidence(self):
        report = _report_with("pricing", {"plans": []})
        trace = real_trace(report)
        assert trace == [{"tool": "web_extractor", "params": {"url": "https://x.com/page"}, "status": "ok"}]


class TestBenchmarkExtractor:
    def test_fails_on_configured_url(self):
        from competitor_agent.domain_types.info_gap import InfoGap
        from competitor_agent.interfaces.context import SourceContext
        from competitor_agent.interfaces.exceptions import DataSourceUnavailableError

        ext = BenchmarkExtractor(page="Pro $20/month", fail_urls={"https://a.com"})
        try:
            ext.fetch(InfoGap(field="pricing"), SourceContext(competitor_name="c", kwargs={"url": "https://a.com"}))
            raised = False
        except DataSourceUnavailableError:
            raised = True
        assert raised

        obs = ext.fetch(InfoGap(field="pricing"), SourceContext(competitor_name="c", kwargs={"url": "https://b.com"}))
        assert obs.raw_text == "Pro $20/month"
        assert obs.evidence.url == "https://b.com"