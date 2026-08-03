"""core/tactical_loop.py 集成测试：mock 数据源跑完整闭环"""
from competitor_agent.analyzers.pricing_analyzer import PricingAnalyzer
from competitor_agent.collector.source_selector import SourceCandidate, SourceSelector
from competitor_agent.core.budget import IterationBudget
from competitor_agent.core.tactical_loop import TacticalLoop
from competitor_agent.domain_types import (
    Competitor,
    CompetitorStrategy,
    GapStatus,
    InfoGap,
    Observation,
    SourceEvidence,
)
from competitor_agent.interfaces.context import SourceContext


class FakeExtractor:
    """给定 URL 返回对应 Observation"""

    def fetch(self, gap: InfoGap, context: SourceContext) -> Observation:
        url = str(context.kwargs.get("url"))
        table = {
            "https://www.cursor.com/pricing": "Pro plan: $20/month, Premier plan: $40/month",
            "https://www.cursor.com": "Cursor the AI code editor",
        }
        text = table.get(url, "")
        ev = SourceEvidence(source_name="web_extractor", url=url, content_hash=str(hash(url)))
        return Observation(gap_field=gap.field, source="web_extractor", raw_text=text, evidence=ev)


class FakeSelector(SourceSelector):
    def __init__(self, candidates):
        self._cands = candidates

    def candidates(self, gap, competitor):
        return self._cands


def _cursor():
    return Competitor(
        name="cursor",
        official_links={"pricing": "https://www.cursor.com/pricing"},
    )


def _make_loop(cands, budget=None, analyzer=None):
    return TacticalLoop(
        selector=FakeSelector(cands),
        extractor=FakeExtractor(),
        analyzer=analyzer or PricingAnalyzer(use_llm=False),
        budget=budget or IterationBudget(max_iterations=5, cost_limit=1.0),
    )


class TestTacticalLoop:
    def test_success_closure(self):
        gap = InfoGap(field="pricing")
        cand = SourceCandidate(source_name="official_pricing", url="https://www.cursor.com/pricing", trust_level=0.9)
        loop = _make_loop([cand])
        strategy = CompetitorStrategy(competitor=_cursor(), gaps=[gap])
        result = loop.execute(gap, strategy)
        assert result is not None
        assert result.dimension == "pricing"
        assert result.details["plans"]  # 检测到来 2 个 plan
        assert gap.status in (GapStatus.PARTIAL, GapStatus.CONFIRMED)
        assert gap.evidence
        assert "official_pricing" in gap.sources_tried

    def test_no_plans_partial(self):
        gap = InfoGap(field="pricing")
        cand = SourceCandidate(source_name="official_home", url="https://www.cursor.com", trust_level=0.9)
        strategy = CompetitorStrategy(competitor=_cursor(), gaps=[gap])
        result = _make_loop([cand]).execute(gap, strategy)
        assert result is not None
        assert result.details["plans"] == []
        assert gap.status == GapStatus.PARTIAL

    def test_degrades_across_sources(self):
        gap = InfoGap(field="pricing")
        bad = SourceCandidate(source_name="official_pricing", url="https://404.com/x", trust_level=0.9)
        good = SourceCandidate(source_name="official_home", url="https://www.cursor.com/pricing", trust_level=0.9)
        strategy = CompetitorStrategy(competitor=_cursor(), gaps=[gap])
        result = _make_loop([bad, good]).execute(gap, strategy)
        assert result is not None

    def test_budget_exhausted_blocks(self):
        gap = InfoGap(field="pricing")
        cand = SourceCandidate(source_name="official_pricing", url="https://www.cursor.com/pricing", trust_level=0.9)
        budget = IterationBudget(max_iterations=0, cost_limit=0.0)
        strategy = CompetitorStrategy(competitor=_cursor(), gaps=[gap])
        result = _make_loop([cand], budget=budget).execute(gap, strategy)
        assert result is None
        assert gap.status == GapStatus.BLOCKED