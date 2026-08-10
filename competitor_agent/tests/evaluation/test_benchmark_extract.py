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

    def test_parse_prompt_falls_back_to_rules(self):
        out = json.loads(BenchmarkMockLLM().complete([
            {"role": "system", "content": "你是竞品分析任务的语义解析器…"},
            {"role": "user", "content": "分析 cursor 定价"},
        ]))
        assert out["competitors"] == []
        assert out["dimensions"] is None


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