"""设计文档 88 §4.1 —— domain_types/distilled 蒸馏层单测。

覆盖：第 0 层原语（pricing 双键形态等价 / plans 畸形容忍 / 双命名空间回退 /
plan_price dict 兜底 / features/benchmarks/ecosystem/sentiment/roadmap 正常与缺省）、
第 1 层 facts 视图（pricing 事实内容 / 未知维度 generic / distill_report 顺序）、
第 2 层 helper（fact_by_term 精确+子串 / numeric_allowlist 三形态）。
"""

from __future__ import annotations

from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.distilled import (
    DistilledFact,
    benchmark_entries,
    benchmark_score,
    distill_dimension,
    distill_report,
    ecosystem_signal,
    fact_by_term,
    feature_present,
    numeric_allowlist,
    plan_price,
    pricing_plans,
    roadmap_events,
    sentiment_signal,
)
from competitor_agent.domain_types.pricing import profile_from_details
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult


class TestPricingPlans:
    def test_two_key_forms_equivalent(self) -> None:
        """monthly_price_usd 与 price+period 两种键形态 → 归一结果一致（与 profile 同源）。"""
        form_a = {"plans": [{"name": "Pro", "monthly_price_usd": 20}]}
        form_b = {"plans": [{"name": "Pro", "price": 20, "period": "month"}]}
        plans_a = pricing_plans(form_a)
        plans_b = pricing_plans(form_b)
        assert [p.monthly_price_usd for p in plans_a] == [20.0]
        assert [p.monthly_price_usd for p in plans_b] == [20.0]
        # 与 profile_from_details 同源（键兼容矩阵唯一权威）
        assert [p.monthly_price_usd for p in profile_from_details(form_a).plans] == [20.0]

    def test_plans_not_list_tolerated(self) -> None:
        assert pricing_plans({"plans": "not-a-list"}) == []
        assert pricing_plans({}) == []

    def test_legacy_pricing_namespace_fallback(self) -> None:
        """旧 details["pricing"]["plans"] 命名空间回退（timeline 历史形态）。"""
        details = {"pricing": {"plans": [{"name": "Pro", "monthly_price_usd": 20}]}}
        plans = pricing_plans(details)
        assert len(plans) == 1 and plans[0].monthly_price_usd == 20.0

    def test_pricing_dict_takes_precedence_over_top_level(self) -> None:
        """timeline 原语义：pricing 为 dict 即取其 plans（顶层被忽略），行为等价硬要求。"""
        details = {
            "plans": [{"name": "Pro", "monthly_price_usd": 20}],
            "pricing": {"plans": [{"name": "Legacy", "monthly_price_usd": 99}]},
        }
        plans = pricing_plans(details)
        assert [p.name for p in plans] == ["Legacy"]

    def test_pricing_dict_without_plans_returns_empty(self) -> None:
        """timeline 原语义：pricing 为 dict 但无 plans → 空（不回退顶层）。"""
        details = {"plans": [{"name": "Pro", "monthly_price_usd": 20}], "pricing": {"as_of": "x"}}
        assert pricing_plans(details) == []


class TestPlanPrice:
    def test_raw_keys_with_period_alias(self) -> None:
        details = {"plans": [{"name": "Pro", "price": "$30", "period": "mo"}]}
        assert plan_price(details, "pro") == "$30/month"

    def test_dict_form_plans_coerced(self) -> None:
        details = {"plans": {"Pro": "30 USD/month"}}
        assert plan_price(details, "pro") == "$30/month"

    def test_missing_term_returns_empty(self) -> None:
        details = {"plans": [{"name": "Pro", "price": "30", "period": "month"}]}
        assert plan_price(details, "enterprise") == ""


class TestOtherPrimitives:
    def test_feature_present(self) -> None:
        details = {"features": ["支持 MCP 协议", "终端集成"]}
        assert feature_present(details, "mcp") == "true"
        assert feature_present(details, "vim") == "false"
        assert feature_present({}, "mcp") == "false"

    def test_benchmark_entries_and_score(self) -> None:
        details = {"benchmarks": [{"name": "MMLU", "score": 0.87}, "junk", {"raw": "SWE-bench: 42"}]}
        entries = benchmark_entries(details)
        assert len(entries) == 2
        assert benchmark_score(details, "mmlu") == "0.87"
        assert benchmark_score(details, "swe-bench") == "42"
        assert benchmark_score({}, "mmlu") == ""

    def test_ecosystem_signals(self) -> None:
        details = {
            "mcp_servers": [{"name": "a"}],
            "plugins": {"count": 120},
            "repo_activity": {"stars": 3000},
            "ide_support": ["VSCode", "Terminal"],
        }
        assert ecosystem_signal(details, "mcp_servers") == 1
        assert ecosystem_signal(details, "plugins") == 120
        assert ecosystem_signal(details, "stars") == 3000
        assert ecosystem_signal(details, "vscode") == "true"
        assert ecosystem_signal(details, "jetbrains") == "false"
        assert ecosystem_signal(details, "ide") == "VSCode Terminal"
        assert ecosystem_signal({}, "mcp_servers") == 0

    def test_sentiment_signals(self) -> None:
        details = {"polarity_ratio": {"pos": 0.6, "neg": 0.1, "neu": 0.3}}
        assert sentiment_signal(details, "polarity") == "pos"
        assert sentiment_signal(details, "positive") == "true"
        assert sentiment_signal(details, "pos") == 0.6
        assert sentiment_signal({}, "polarity") == "neu"
        assert sentiment_signal({}, "positive") == "false"

    def test_roadmap_events(self) -> None:
        details = {"events": [{"title": "v2 发布", "date": "2026-06"}, "junk"]}
        assert roadmap_events(details) == [{"title": "v2 发布", "date": "2026-06"}]
        assert roadmap_events({}) == []


def _dim(dimension: str, details: dict, **kw: object) -> DimensionResult:
    return DimensionResult(dimension=dimension, details=details, **kw)  # type: ignore[arg-type]


class TestDistillView:
    def test_pricing_facts(self) -> None:
        result = _dim(
            "pricing",
            {"plans": [{"name": "Pro", "monthly_price_usd": 20}]},
            summary="定价结论",
            confidence=0.8,
        )
        df = distill_dimension(result)
        assert df.dimension == "pricing"
        assert df.confidence == 0.8
        monthly = fact_by_term(df.facts, "plan:pro:monthly")
        assert monthly is not None
        assert monthly.numeric == 20.0
        assert monthly.unit == "USD/month"

    def test_unknown_dimension_generic_scalars(self) -> None:
        result = _dim("custom", {"users": 1000, "note": "增长迅速", "nested": {"a": 1}})
        df = distill_dimension(result)
        terms = {f.term for f in df.facts}
        assert terms == {"users", "note"}  # 嵌套 dict 不进 generic

    def test_distill_report_order(self) -> None:
        report = CompetitorReport(
            competitor=Competitor(name="x"),
            dimension_results=[_dim("feature", {}), _dim("pricing", {})],
        )
        assert [d.dimension for d in distill_report(report)] == ["feature", "pricing"]


class TestHelpers:
    def test_fact_by_term_exact_then_substring(self) -> None:
        facts = [
            DistilledFact(term="plan:pro:monthly", label="Pro 档月价", value="20", numeric=20.0),
            DistilledFact(term="benchmark:MMLU", label="MMLU 得分", value="0.87", numeric=0.87),
        ]
        assert fact_by_term(facts, "plan:pro:monthly") is facts[0]
        assert fact_by_term(facts, "mmlu") is facts[1]
        assert fact_by_term(facts, "不存在") is None

    def test_numeric_allowlist_three_forms(self) -> None:
        facts = [
            DistilledFact(term="a", label="a", value="20", numeric=20.0),
            DistilledFact(term="b", label="b", value="20.5", numeric=20.5),
            DistilledFact(term="c", label="c", value="x"),  # 无数值不进集合
        ]
        allowed = numeric_allowlist(facts)
        assert {"20", "20.00"} <= allowed
        assert {"20.5", "20.50"} <= allowed
