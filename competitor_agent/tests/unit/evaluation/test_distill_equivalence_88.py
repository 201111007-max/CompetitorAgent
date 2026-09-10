"""设计文档 88 §4.1 —— 蒸馏层切换的等价性基线（C1 测试先行）。

切换前：断言「旧实现输出 == 蒸馏原语输出 == 字面期望」三重等价（此时消费点仍跑旧实现，
本文件自证基线）；C2 切换后删除旧实现一侧，字面期望保留为蒸馏原语的回归网。

覆盖：benchmark 五分支（plan_price 三种 plans 形态 / feature_present / benchmark_score
两种形态 / ecosystem_signal 全键 / sentiment_signal 全键）+ report_exporter benchmarks
透传 + timeline_memory 定价标签（双命名空间/需询价/截断）。
"""

from __future__ import annotations

from typing import Any

import pytest
from competitor_agent.core import report_exporter
from competitor_agent.domain_types import distilled
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult
from competitor_agent.evaluation import benchmark as bench
from competitor_agent.memory import timeline_memory

# ── benchmark 五分支：fixture = (details, key/term, 字面期望) ──────────────

_PLAN_PRICE_CASES: list[tuple[dict[str, Any], str, str]] = [
    ({"plans": [{"name": "Pro", "price": "$20", "period": "mo"}]}, "pro", "$20/month"),
    ({"plans": [{"name": "Pro", "price": "200", "period": "year"}]}, "pro", "$200/year"),
    ({"plans": [{"name": "Pro", "price": "20"}]}, "pro", "$20"),
    ({"plans": {"Pro": "30 USD/month"}}, "pro", "$30/month"),  # real 轨字典形态
    ({"plans": {"Pro": {"price": "30", "period": "month"}}}, "pro", "$30/month"),
    ({"plans": ["junk", {"name": "Pro", "price": "10", "period": "month"}]}, "pro", "$10/month"),
    ({"plans": [{"name": "Pro", "price": "20", "period": "month"}]}, "enterprise", ""),
    ({}, "pro", ""),
]

_FEATURE_CASES: list[tuple[dict[str, Any], str, str]] = [
    ({"features": ["支持 MCP 协议", "终端集成"]}, "mcp", "true"),
    ({"features": ["支持 MCP 协议"]}, "vim", "false"),
    ({"features": "not-a-list"}, "mcp", "false"),
    ({}, "mcp", "false"),
]

_BENCHMARK_SCORE_CASES: list[tuple[dict[str, Any], str, str]] = [
    ({"benchmarks": [{"name": "MMLU", "score": 0.87}]}, "mmlu", "0.87"),
    ({"benchmarks": [{"raw": "SWE-bench: 42"}]}, "swe-bench", "42"),
    ({"benchmarks": [{"raw": "no-colon-line"}]}, "no-colon", "no-colon-line"),
    ({"benchmarks": ["junk", {"name": "MMLU", "score": 0.5}]}, "mmlu", "0.5"),
    ({"benchmarks": [{"name": "MMLU", "score": 0.87}]}, "gpqa", ""),
    ({}, "mmlu", ""),
]

_ECOSYSTEM_DETAILS: dict[str, Any] = {
    "mcp_servers": [{"name": "a"}, {"name": "b"}],
    "plugins": {"count": 120},
    "repo_activity": {"stars": 3000},
    "ide_support": ["VSCode", "Terminal"],
}
_ECOSYSTEM_CASES: list[tuple[dict[str, Any], str, Any]] = [
    (_ECOSYSTEM_DETAILS, "mcp_servers", 2),
    (_ECOSYSTEM_DETAILS, "plugins", 120),
    (_ECOSYSTEM_DETAILS, "stars", 3000),
    (_ECOSYSTEM_DETAILS, "vscode", "true"),
    (_ECOSYSTEM_DETAILS, "jetbrains", "false"),
    (_ECOSYSTEM_DETAILS, "terminal", "true"),
    (_ECOSYSTEM_DETAILS, "ide", "VSCode Terminal"),
    (_ECOSYSTEM_DETAILS, "unknown_key", ""),
    ({"plugins": "not-a-dict", "repo_activity": "x"}, "plugins", 0),
    ({}, "mcp_servers", 0),
]

_SENTIMENT_DETAILS: dict[str, Any] = {"polarity_ratio": {"pos": 0.6, "neg": 0.1, "neu": 0.3}}
_SENTIMENT_CASES: list[tuple[dict[str, Any], str, Any]] = [
    (_SENTIMENT_DETAILS, "polarity", "pos"),
    ({"polarity_ratio": {"pos": 0.1, "neg": 0.6, "neu": 0.3}}, "polarity", "neg"),
    ({"polarity_ratio": {"pos": 0.1, "neg": 0.2, "neu": 0.7}}, "polarity", "neu"),
    (_SENTIMENT_DETAILS, "positive", "true"),
    (_SENTIMENT_DETAILS, "negative", "true"),
    (_SENTIMENT_DETAILS, "neutral", "true"),
    (_SENTIMENT_DETAILS, "pos", 0.6),
    (_SENTIMENT_DETAILS, "neg", 0.1),
    (_SENTIMENT_DETAILS, "unknown_key", ""),
    ({}, "polarity", "neu"),
    ({}, "positive", "false"),
    ({"polarity_ratio": "not-a-dict"}, "pos", 0.0),
]


class TestBenchmarkBranchEquivalence:
    @pytest.mark.parametrize(("details", "term", "expected"), _PLAN_PRICE_CASES)
    def test_plan_price(self, details: dict[str, Any], term: str, expected: str) -> None:
        assert bench._plan_price(details, term) == expected
        assert distilled.plan_price(details, term) == expected

    @pytest.mark.parametrize(("details", "term", "expected"), _FEATURE_CASES)
    def test_feature_present(self, details: dict[str, Any], term: str, expected: str) -> None:
        assert bench._feature_present(details, term) == expected
        assert distilled.feature_present(details, term) == expected

    @pytest.mark.parametrize(("details", "term", "expected"), _BENCHMARK_SCORE_CASES)
    def test_benchmark_score(self, details: dict[str, Any], term: str, expected: str) -> None:
        assert bench._benchmark_score(details, term) == expected
        assert distilled.benchmark_score(details, term) == expected

    @pytest.mark.parametrize(("details", "key", "expected"), _ECOSYSTEM_CASES)
    def test_ecosystem_signal(self, details: dict[str, Any], key: str, expected: Any) -> None:
        assert bench._ecosystem_signal(details, key) == expected
        assert distilled.ecosystem_signal(details, key) == expected

    @pytest.mark.parametrize(("details", "key", "expected"), _SENTIMENT_CASES)
    def test_sentiment_signal(self, details: dict[str, Any], key: str, expected: Any) -> None:
        assert bench._sentiment_signal(details, key) == expected
        assert distilled.sentiment_signal(details, key) == expected


class TestExporterEquivalence:
    def _report(self, details: dict[str, Any]) -> CompetitorReport:
        return CompetitorReport(
            competitor=Competitor(name="x"),
            dimension_results=[DimensionResult(dimension="performance", details=details)],
        )

    def test_benchmark_scores_passthrough(self) -> None:
        details = {"benchmarks": [{"name": "MMLU", "score": 0.87}, "junk", {"raw": "r"}]}
        expected = [{"name": "MMLU", "score": 0.87}, {"raw": "r"}]
        assert report_exporter._benchmark_scores(self._report(details)) == expected
        assert distilled.benchmark_entries(details) == expected

    def test_benchmark_scores_malformed(self) -> None:
        assert report_exporter._benchmark_scores(self._report({"benchmarks": "x"})) == []
        assert distilled.benchmark_entries({"benchmarks": "x"}) == []
        assert report_exporter._benchmark_scores(self._report({})) == []
        assert distilled.benchmark_entries({}) == []


_TIMELINE_CASES: list[tuple[dict[str, Any], str]] = [
    (
        {"details": {"plans": [{"name": "Pro", "monthly_price_usd": 20}]}},
        "pro: $20/mo",
    ),
    (
        {"details": {"pricing": {"plans": [{"name": "Pro", "monthly_price_usd": 20}]}}},
        "pro: $20/mo",
    ),
    (
        {"details": {"plans": [{"name": "Enterprise", "requires_quote": True}]}},
        "enterprise: 需询价",
    ),
    (
        {
            "details": {
                "plans": [
                    {"name": "Free", "monthly_price_usd": 0},
                    {"name": "Pro", "monthly_price_usd": 20},
                    {"name": "Business", "monthly_price_usd": 40},
                    {"name": "Enterprise", "monthly_price_usd": 100},
                    {"name": "Ultimate", "monthly_price_usd": 200},
                ]
            }
        },
        "free: $0/mo；pro: $20/mo；business: $40/mo；enterprise: $100/mo",  # parts[:4] 截断
    ),
    ({"details": {}}, ""),
    ({"details": {"plans": "not-a-list"}}, ""),
]


class TestTimelineEquivalence:
    """timeline `_pricing_price_label` 旧实现 vs 基于 pricing_plans 的重实现（C2 目标形态）。"""

    @staticmethod
    def _new_label(snapshot: dict[str, Any]) -> str:
        details = snapshot.get("details") or {}
        if not isinstance(details, dict):
            details = {}
        parts: list[str] = []
        for plan in distilled.pricing_plans(details):
            if plan.requires_quote:
                parts.append(f"{plan.tier}: 需询价")
                continue
            if plan.monthly_price_usd is not None:
                parts.append(f"{plan.tier}: ${plan.monthly_price_usd:g}/mo")
        return "；".join(parts[:4])

    @pytest.mark.parametrize(("snapshot", "expected"), _TIMELINE_CASES)
    def test_pricing_price_label(self, snapshot: dict[str, Any], expected: str) -> None:
        assert timeline_memory._pricing_price_label(snapshot) == expected
        assert self._new_label(snapshot) == expected
