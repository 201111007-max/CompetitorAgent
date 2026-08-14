"""分析器结构化抽取单测（设计文档 34）

覆盖：各维度 _schema_for/_details_properties 与评测 extract_prediction 抽取键对齐
（防契约漂移）、真值校验惩罚（数值与原文冲突 → 降置信度 → [PARTIAL]）、
半合法 JSON 修复重试（而非降级规则）、schema 校验耗尽降级规则。
"""
from __future__ import annotations

import json

from competitor_agent.analyzers import (
    EcosystemAnalyzer,
    FeatureAnalyzer,
    PerformanceAnalyzer,
    PricingAnalyzer,
    SentimentAnalyzer,
)
from competitor_agent.domain_types import InfoGap, Observation, SourceEvidence
from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.interfaces.context import AnalysisContext
from competitor_agent.llm.client import LLMClient


def _obs(raw_text, gap_field="pricing"):
    ev = SourceEvidence(source_name="web_extractor", content_hash="h1")
    return Observation(gap_field=gap_field, source="web_extractor", raw_text=raw_text, evidence=ev)


def _schema_keys(analyzer):
    return set(analyzer._details_properties())


class TestSchemaAlignedWithEvaluation:
    """各维度 schema 声明键与 extract_prediction 可抽取键对齐（设计文档 34 §5）"""

    def test_pricing_schema_has_plans(self):
        assert "plans" in _schema_keys(PricingAnalyzer())

    def test_feature_schema_has_features(self):
        assert "features" in _schema_keys(FeatureAnalyzer())

    def test_performance_schema_has_benchmarks(self):
        assert "benchmarks" in _schema_keys(PerformanceAnalyzer())

    def test_ecosystem_schema_keys(self):
        keys = _schema_keys(EcosystemAnalyzer())
        for required in ("mcp_servers", "plugins", "ide_support", "repo_activity"):
            assert required in keys

    def test_sentiment_schema_keys(self):
        keys = _schema_keys(SentimentAnalyzer())
        for required in ("signals", "polarity_ratio", "verdict"):
            assert required in keys


class TestVerifyDetails:
    def test_conflict_lowers_confidence_to_partial(self):
        """LLM 编造实体数值（原文无）→ 真值校验惩罚 → [PARTIAL]"""
        def fake_llm(messages, model):
            return json.dumps(
                {
                    "summary": "ecosystem",
                    "details": {
                        "mcp_servers": [],
                        "plugins": {"count": 3, "rating": 0, "top": []},
                        "ide_support": ["vscode"],
                        "integrations": [],
                        "repo_activity": {"stars": 100, "last_release": "", "commits_30d": 5},
                    },
                    "confidence": 0.9,
                }
            )

        a = EcosystemAnalyzer(llm=LLMClient(call_func=fake_llm))
        obs = _obs("just marketing copy with no numbers", "ecosystem")
        result = a.analyze(obs, InfoGap(field="ecosystem"), AnalysisContext())
        assert result.confidence < 0.5
        assert result.status == ResultStatus.PARTIAL

    def test_consistent_value_no_penalty(self):
        """数值与原文一致 → 不惩罚 → COMPLETE"""
        def fake_llm(messages, model):
            return json.dumps(
                {
                    "summary": "pricing",
                    "details": {"plans": [{"name": "pro", "monthly_price_usd": 20}]},
                    "confidence": 0.9,
                }
            )

        a = PricingAnalyzer(llm=LLMClient(call_func=fake_llm))
        obs = _obs("Pro plan $20/month", "pricing")
        result = a.analyze(obs, InfoGap(field="pricing"), AnalysisContext())
        assert result.confidence == 0.9
        assert result.status == ResultStatus.COMPLETE

    def test_zero_value_not_penalized(self):
        """0 值是"无信号"缺省，不视为编造"""
        def fake_llm(messages, model):
            return json.dumps(
                {
                    "summary": "ecosystem",
                    "details": {
                        "mcp_servers": [],
                        "plugins": {"count": 0, "rating": 0, "top": []},
                        "ide_support": [],
                        "integrations": [],
                        "repo_activity": {"stars": 0, "last_release": "", "commits_30d": 0},
                    },
                    "confidence": 0.7,
                }
            )

        a = EcosystemAnalyzer(llm=LLMClient(call_func=fake_llm))
        obs = _obs("no signals here", "ecosystem")
        result = a.analyze(obs, InfoGap(field="ecosystem"), AnalysisContext())
        assert result.confidence == 0.7

    def test_commma_thousands_matches(self):
        """"12,000 stars" ↔ 12000 视为一致（忽略标点差异）"""
        def fake_llm(messages, model):
            return json.dumps(
                {
                    "summary": "ecosystem",
                    "details": {
                        "mcp_servers": [],
                        "plugins": {"count": 0, "rating": 0, "top": []},
                        "ide_support": ["vscode"],
                        "integrations": [],
                        "repo_activity": {"stars": 12000, "last_release": "", "commits_30d": 0},
                    },
                    "confidence": 0.8,
                }
            )

        a = EcosystemAnalyzer(llm=LLMClient(call_func=fake_llm))
        obs = _obs("Stars: 12,000\nsupports vscode", "ecosystem")
        result = a.analyze(obs, InfoGap(field="ecosystem"), AnalysisContext())
        assert result.confidence == 0.8


class TestSchemaRepairRetry:
    def test_type_mismatch_repairs_not_degrade(self):
        """LLM 输出 confidence 类型错 → 修复重试成功（而非降级规则）"""
        seen = []

        def fake_llm(messages, model):
            seen.append(messages)
            if len(seen) == 1:
                return json.dumps(
                    {"summary": "s", "details": {"features": ["MCP"]}, "confidence": "high"}
                )
            return json.dumps(
                {"summary": "s", "details": {"features": ["MCP"]}, "confidence": 0.9}
            )

        a = FeatureAnalyzer(llm=LLMClient(call_func=fake_llm))
        obs = _obs("Supports MCP integration", "feature")
        result = a.analyze(obs, InfoGap(field="feature"), AnalysisContext())
        assert result.confidence == 0.9
        assert result.details["features"] == ["MCP"]
        assert len(seen) == 2

    def test_schema_failure_falls_back_to_rules(self):
        """schema 校验耗尽（缺 confidence）→ 降级规则提取"""
        def fake_llm(messages, model):
            return json.dumps({"summary": "s", "details": {}})  # 永远缺 confidence

        a = PricingAnalyzer(llm=LLMClient(call_func=fake_llm))
        obs = _obs("Pro plan: $20/month", "pricing")
        result = a.analyze(obs, InfoGap(field="pricing"), AnalysisContext())
        assert result.details["plans"]  # 来自规则降级
        assert result.confidence == 0.5
