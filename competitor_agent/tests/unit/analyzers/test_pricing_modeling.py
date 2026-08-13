"""设计文档 27 §5 单测（pricing modeling）：结构抽取 / 成本估算 / 询价标注 / 渲染 / 时间线 diff"""
from __future__ import annotations

import json

from competitor_agent.analyzers import PricingAnalyzer
from competitor_agent.core.markdown_renderer import MarkdownRenderer
from competitor_agent.domain_types import InfoGap, Observation, PricingProfile, SourceEvidence
from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.domain_types.pricing import PricingPlan, UsageBilling
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult
from competitor_agent.interfaces.context import AnalysisContext
from competitor_agent.llm.client import LLMClient
from competitor_agent.memory.timeline_memory import TimelineMemory

_STRUCTURE_TEXT = (
    "Free $0\nPro $20/month\nTeams $40/month\nUltra $60/month\n"
    "per 1000 requests $0.5\nincludes 1000 requests/month\nAdvanced model $2.00/request"
)


def _obs(raw_text: str) -> Observation:
    ev = SourceEvidence(source_name="web_extractor", url="https://cursor.test/pricing", content_hash="h")
    return Observation(gap_field="pricing", source="web_extractor", raw_text=raw_text, evidence=ev)


class TestStructureExtraction:
    def test_rule_extract_full_structure(self) -> None:
        a = PricingAnalyzer(use_llm=False)
        result = a.analyze(_obs(_STRUCTURE_TEXT), InfoGap(field="pricing"), AnalysisContext())
        profile = PricingProfile.from_dict(result.details["pricing"])
        assert [p.monthly_price_usd for p in profile.plans] == [0.0, 20.0, 40.0, 60.0]
        assert [p.tier for p in profile.plans] == ["free", "pro", "business", "plan"]
        assert profile.usage is not None
        assert profile.usage.per_unit_usd == 0.0005  # 每千请求 $0.5 → 每请求 $0.0005
        assert profile.usage.included_units == 1000
        assert profile.usage.model_tiers == {"advanced": 2.0}

    def test_rule_keeps_legacy_plan_keys(self) -> None:
        """plans[].price/period 保留，兼容评测与既有渲染契约。"""
        a = PricingAnalyzer(use_llm=False)
        result = a.analyze(_obs("Pro $20/month"), InfoGap(field="pricing"), AnalysisContext())
        assert result.details["plans"][0]["price"] == "20"
        assert result.details["plans"][0]["period"] == "month"

    def test_llm_legacy_shape_parsed(self) -> None:
        def fake_llm(messages, model):
            return json.dumps(
                {
                    "summary": "2 plans",
                    "details": {"plans": [{"name": "Pro", "price": "20", "period": "month"}]},
                    "confidence": 0.9,
                }
            )

        a = PricingAnalyzer(llm=LLMClient(call_func=fake_llm))
        result = a.analyze(_obs("Pro $20/mo"), InfoGap(field="pricing"), AnalysisContext())
        profile = PricingProfile.from_dict(result.details["pricing"])
        assert profile.plans[0].monthly_price_usd == 20.0
        assert result.confidence == 0.9

    def test_llm_structured_shape_parsed(self) -> None:
        def fake_llm(messages, model):
            return json.dumps(
                {
                    "summary": "structured",
                    "details": {
                        "plans": [{"name": "Pro", "tier": "pro", "monthly_price": 20, "annual_price": 200}],
                        "usage": {"unit": "request", "per_unit_price": 0.005, "quantity": 1000},
                    },
                    "confidence": 0.85,
                }
            )

        a = PricingAnalyzer(llm=LLMClient(call_func=fake_llm))
        result = a.analyze(_obs("Pro $20/mo"), InfoGap(field="pricing"), AnalysisContext())
        profile = PricingProfile.from_dict(result.details["pricing"])
        assert profile.plans[0].tier == "pro"
        assert profile.plans[0].annual_price_usd == 200.0
        assert profile.usage is not None and profile.usage.per_unit_usd == 0.005

    def test_no_data_marks_partial_without_fabrication(self) -> None:
        a = PricingAnalyzer(use_llm=False)
        result = a.analyze(_obs("just marketing copy"), InfoGap(field="pricing"), AnalysisContext())
        assert result.details["plans"] == []
        assert result.status == ResultStatus.PARTIAL
        assert result.confidence == 0.3
        assert "未检测到定价信息" in result.summary
        assert result.details["pricing"]["cost_scenarios"] == {}


class TestCostEstimation:
    def test_within_limit_equals_plan_price(self) -> None:
        a = PricingAnalyzer(use_llm=False)
        result = a.analyze(
            _obs("Pro $20/month\nper 1000 requests $0.5\nincludes 1000 requests/month"),
            InfoGap(field="pricing"),
            AnalysisContext(),
        )
        costs = result.details["pricing"]["cost_scenarios"]
        assert costs["light"] == 20.0  # 900 次/月 ≤ 1000 档内包含 → 档价
        assert costs["medium"] == 21.0  # 3000 次/月 → 档价 + 2000×$0.0005
        assert costs["heavy"] == 34.5  # 30000 次/月 → 档价 + 29000×$0.0005

    def test_no_per_unit_within_limit_price_no_overage(self) -> None:
        a = PricingAnalyzer(use_llm=False)
        result = a.analyze(
            _obs("Pro $20/month (1000 requests/month)"),
            InfoGap(field="pricing"),
            AnalysisContext(),
        )
        costs = result.details["pricing"]["cost_scenarios"]
        assert costs["light"] == 20.0
        assert costs["medium"] is None  # 超限额且无按量单价：不编造
        assert costs["heavy"] is None

    def test_cheapest_plan_selected(self) -> None:
        a = PricingAnalyzer(use_llm=False)
        result = a.analyze(
            _obs("Free $0\nPro $20/month\nTeams $40/month\nUltra $60/month\nper 1000 requests $0.5\nincludes 1000 requests/month"),
            InfoGap(field="pricing"),
            AnalysisContext(),
        )
        costs = result.details["pricing"]["cost_scenarios"]
        assert costs["light"] == 0.0
        assert costs["medium"] == 1.0  # 免费档 2000×$0.0005
        assert costs["heavy"] == 14.5  # 免费档 29000×$0.0005

    def test_enterprise_quote_not_guessed(self) -> None:
        a = PricingAnalyzer(use_llm=False)
        result = a.analyze(
            _obs("Pro $20/month\nEnterprise (contact sales)"),
            InfoGap(field="pricing"),
            AnalysisContext(),
        )
        profile = PricingProfile.from_dict(result.details["pricing"])
        ent = [p for p in profile.plans if p.tier == "enterprise"]
        assert ent and ent[0].requires_quote is True
        assert ent[0].monthly_price_usd is None
        assert "需询价" in result.summary


class TestPricingProfileSerialization:
    def test_roundtrip(self) -> None:
        profile = PricingProfile(
            plans=[PricingPlan(tier="pro", name="Pro", monthly_price_usd=20.0, requires_quote=False)],
            usage=UsageBilling(unit="request", per_unit_usd=0.0005, included_units=1000),
            cost_scenarios={"light": 20.0, "medium": 21.0, "heavy": None},
            as_of="2026-08-13T00:00:00+00:00",
            source_urls=["https://cursor.test/pricing"],
        )
        assert PricingProfile.from_dict(profile.to_dict()) == profile
        assert PricingProfile.from_dict(None) is None


class TestPricingRendering:
    def _render(self, text: str) -> str:
        a = PricingAnalyzer(use_llm=False)
        result = a.analyze(_obs(text), InfoGap(field="pricing"), AnalysisContext())
        report = CompetitorReport(competitor=_competitor("cursor"), dimension_results=[result])
        return MarkdownRenderer().render(report)

    def test_render_pricing_tables(self) -> None:
        md = self._render(_STRUCTURE_TEXT)
        assert "#### 定价档位" in md
        assert "#### 按量计费" in md
        assert "#### 成本场景估算" in md
        assert "| 档位 | 计划 | 月付 (USD) | 年付 (USD) | 限额 | 询价 |" in md
        assert "| light | 30 次/天 | $0 |" in md

    def test_render_quote_plan(self) -> None:
        md = self._render("Pro $20/month\nEnterprise (contact sales)")
        assert "需询价" in md

    def test_render_no_data_falls_back_to_blob(self) -> None:
        md = self._render("no pricing data at all")
        assert "明细:" in md
        assert "未检测到定价信息" in md


class TestPricingTimelineDiff:
    def _report(self, prices: list[float], as_of: str) -> CompetitorReport:
        plans = [
            {
                "tier": "pro",
                "name": "Pro",
                "monthly_price_usd": p,
                "annual_price_usd": None,
                "limits": {},
                "requires_quote": False,
            }
            for p in prices
        ]
        result = DimensionResult(
            dimension="pricing",
            summary="pricing",
            details={"pricing": {"plans": plans, "usage": None, "cost_scenarios": {}, "as_of": as_of, "source_urls": []}},
            confidence=0.8,
        )
        return CompetitorReport(competitor=_competitor("cursor"), dimension_results=[result])

    def test_price_change_event(self) -> None:
        events = TimelineMemory.diff(
            self._report([20.0], "2026-08-01T00:00:00+00:00"),
            self._report([40.0], "2026-08-13T00:00:00+00:00"),
        )
        assert events
        assert events[0].event_type == "price_change"
        assert "价格变化" in events[0].summary
        assert "$20" in events[0].summary and "$40" in events[0].summary

    def test_unchanged_price_no_event_despite_as_of_drift(self) -> None:
        """as_of 每次分析都会变化，归一化后不应产生伪事件。"""
        events = TimelineMemory.diff(
            self._report([20.0], "2026-08-01T00:00:00+00:00"),
            self._report([20.0], "2026-08-13T00:00:00+00:00"),
        )
        assert events == []


def _competitor(name: str):
    from competitor_agent.domain_types.competitor import Competitor

    return Competitor(name=name)