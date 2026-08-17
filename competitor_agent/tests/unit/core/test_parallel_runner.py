"""core/subagent.py + parallel_runner.py 测试（M3 3.6）"""
import threading
import time

from competitor_agent.analyzers.pricing_analyzer import PricingAnalyzer
from competitor_agent.analyzers.registry import AnalyzerRegistry
from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.core.budget import IterationBudget
from competitor_agent.core.parallel_runner import ParallelRunner
from competitor_agent.core.subagent import SubAgent
from competitor_agent.domain_types import (
    Competitor,
    CompetitorStrategy,
    InfoGap,
    Observation,
    SourceEvidence,
)
from competitor_agent.interfaces.context import SourceContext


class SlowExtractor:
    """模拟耗时抓取，用于验证并行加速"""

    source_name = "web_extractor"

    def __init__(self, delay: float = 0.1) -> None:
        self._delay = delay

    def is_available(self) -> bool:
        return True

    def fetch(self, gap: InfoGap, context: SourceContext) -> Observation:
        time.sleep(self._delay)
        ev = SourceEvidence(source_name=self.source_name, url=str(context.kwargs.get("url")), trust_level=0.9)
        return Observation(gap_field=gap.field, source=self.source_name, raw_text=f"{gap.field} 详细内容", evidence=ev)


def _strategy(fields=("pricing", "feature", "performance")):
    comp = Competitor(
        name="cursor",
        official_links={
            "home": "https://www.cursor.com",
            "pricing": "https://www.cursor.com/pricing",
            "docs": "https://docs.cursor.com",
        },
    )
    return CompetitorStrategy(competitor=comp, gaps=[InfoGap(field=f) for f in fields])


def _make_subagent(extractor, mock_llm):
    registry = AnalyzerRegistry(llm=mock_llm, use_llm=True)

    def factory(gap: InfoGap, strategy: CompetitorStrategy) -> SubAgent:
        return SubAgent(
            gap=gap,
            strategy=strategy,
            selector=SourceSelector(),
            extractor=extractor,
            analyzer=registry.get(gap.field),
            budget=IterationBudget(max_iterations=5, cost_limit=1.0),
        )

    return factory


class TestSubAgent:
    def test_single_gap_closure(self, mock_llm):
        gap = InfoGap(field="pricing")
        strategy = _strategy(("pricing",))
        sub = SubAgent(
            gap=gap,
            strategy=strategy,
            selector=SourceSelector(),
            extractor=SlowExtractor(),
            analyzer=PricingAnalyzer(llm=mock_llm, use_llm=True),
            budget=IterationBudget(max_iterations=5, cost_limit=1.0),
        )
        result = sub.run()
        assert result is not None
        assert result.dimension == "pricing"
        assert gap.evidence  # 证据已挂回缺口


class TestParallelRunner:
    def test_parallel_merges_results_in_order(self, mock_llm):
        factory = _make_subagent(SlowExtractor(delay=0.05), mock_llm)
        strategy = _strategy()
        runner = ParallelRunner(factory, max_workers=4)
        results = runner.run(strategy)
        assert [r.dimension for r in results] == ["pricing", "feature", "performance"]

    def test_parallel_faster_than_serial(self, mock_llm):
        factory = _make_subagent(SlowExtractor(delay=0.15), mock_llm)
        strategy = _strategy(("pricing", "feature", "performance"))
        runner = ParallelRunner(factory, max_workers=3)

        start = time.monotonic()
        runner.run(strategy)
        parallel_elapsed = time.monotonic() - start

        assert parallel_elapsed < 0.4  # 3 个 0.15s 任务并行应显著快于 0.45s 串行

    def test_shared_budget_is_thread_safe(self, mock_llm):
        budget = IterationBudget(max_iterations=20, cost_limit=1.0, min_continuations=999)
        seen = set()
        lock = threading.Lock()

        class ThreadedExtractor(SlowExtractor):
            def fetch(self, gap, context):
                with lock:
                    seen.add(gap.field)
                return super().fetch(gap, context)

        registry = AnalyzerRegistry(llm=mock_llm, use_llm=True)

        def factory(gap: InfoGap, strategy: CompetitorStrategy) -> SubAgent:
            return SubAgent(
                gap=gap,
                strategy=strategy,
                selector=SourceSelector(),
                extractor=ThreadedExtractor(delay=0.02),
                analyzer=registry.get(gap.field),
                budget=budget,
            )

        strategy = _strategy(("pricing", "feature", "performance", "ecosystem", "sentiment", "roadmap"))
        runner = ParallelRunner(factory, max_workers=6)
        results = runner.run(strategy)
        assert len(results) >= 3
        assert seen == {g.field for g in strategy.gaps}
