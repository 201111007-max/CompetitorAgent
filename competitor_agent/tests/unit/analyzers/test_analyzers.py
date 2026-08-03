"""analyzers 单测：规则降级 + LLM 注入两种路径"""
import json

from competitor_agent.analyzers import (
    FallbackAnalyzer,
    FeatureAnalyzer,
    PerformanceAnalyzer,
    PricingAnalyzer,
)
from competitor_agent.domain_types import InfoGap, Observation, SourceEvidence
from competitor_agent.interfaces.context import AnalysisContext
from competitor_agent.llm.client import LLMClient


def _obs(raw_text, gap_field="pricing"):
    ev = SourceEvidence(source_name="web_extractor", content_hash="h1")
    return Observation(gap_field=gap_field, source="web_extractor", raw_text=raw_text, evidence=ev)


class TestPricingAnalyzer:
    def test_rule_extract_finds_plans(self):
        a = PricingAnalyzer(use_llm=False)
        obs = _obs("Pro plan: $20/month\nTeam plan: $40/month")
        result = a.analyze(obs, InfoGap(field="pricing"), AnalysisContext())
        assert result.dimension == "pricing"
        assert len(result.details["plans"]) == 2
        assert result.confidence == 0.5

    def test_rule_extract_no_price_returns_empty(self):
        a = PricingAnalyzer(use_llm=False)
        obs = _obs("no pricing info here at all")
        result = a.analyze(obs, InfoGap(field="pricing"), AnalysisContext())
        assert result.details["plans"] == []

    def test_llm_path_used(self):
        def fake_llm(messages, model):
            return json.dumps(
                {"summary": "2 plans", "details": {"plans": [{"name": "Pro", "price": "20"}]}, "confidence": 0.9}
            )

        a = PricingAnalyzer(llm=LLMClient(call_func=fake_llm))
        obs = _obs("Pro $20/mo")
        result = a.analyze(obs, InfoGap(field="pricing"), AnalysisContext())
        assert result.confidence == 0.9
        assert result.details["plans"][0]["name"] == "Pro"

    def test_llm_failure_falls_back_to_rules(self):
        class FailingLLM(LLMClient):
            def complete(self, messages):
                raise RuntimeError("llm down")

        a = PricingAnalyzer(llm=FailingLLM())
        obs = _obs("Pro plan: $20/month")
        result = a.analyze(obs, InfoGap(field="pricing"), AnalysisContext())
        assert len(result.details["plans"]) == 1
        assert result.confidence == 0.5  # 降级规则


class TestFeatureAnalyzer:
    def test_rule_extract_features(self):
        a = FeatureAnalyzer(use_llm=False)
        obs = _obs(
            "Supports MCP integration\nAdvanced agent terminal mode\nReview code faster",
            gap_field="feature",
        )
        result = a.analyze(obs, InfoGap(field="feature"), AnalysisContext())
        assert result.dimension == "feature"
        assert len(result.details["features"]) >= 2


class TestPerformanceAnalyzer:
    def test_rule_extract_benchmarks(self):
        a = PerformanceAnalyzer(use_llm=False)
        obs = _obs(
            "SWE-bench: 62.0% resolved\nAider polyglot: 57.4%",
            gap_field="performance",
        )
        result = a.analyze(obs, InfoGap(field="performance"), AnalysisContext())
        assert result.dimension == "performance"
        assert len(result.details["benchmarks"]) == 2

    def test_no_benchmark_returns_empty(self):
        a = PerformanceAnalyzer(use_llm=False)
        obs = _obs("just marketing copy", gap_field="performance")
        result = a.analyze(obs, InfoGap(field="performance"), AnalysisContext())
        assert result.details["benchmarks"] == []


class TestFallbackAnalyzer:
    def test_returns_summary_with_low_confidence(self):
        a = FallbackAnalyzer(use_llm=False)
        obs = _obs("Some raw text about anything")
        result = a.analyze(obs, InfoGap(field="pricing"), AnalysisContext())
        assert result.confidence == 0.3
        assert result.summary == "Some raw text about anything"


class TestConfidenceContract:
    def test_confidence_method(self):
        a = PricingAnalyzer(use_llm=False)
        result = a.analyze(_obs("Pro $20/mo"), InfoGap(field="pricing"), AnalysisContext())
        assert a.confidence(result) == result.confidence