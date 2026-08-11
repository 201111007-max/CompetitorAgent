"""core/gap_executor.py 单测：选源 / 降级 / 分析 / 预算 / 取消 / RAG 分支

问题 12.1 消重的回归保障：TacticalLoop / SubAgent / CollectorAgent 共用 GapExecutor
（及 fetch_candidate），此处覆盖统一闭环的关键分支，保证各路径行为一致。
"""

from __future__ import annotations

from types import SimpleNamespace

from competitor_agent.collector.source_selector import SourceCandidate, SourceSelector
from competitor_agent.core.budget import IterationBudget
from competitor_agent.core.checkpoint import clear_cancel, set_cancel
from competitor_agent.core.gap_executor import GapExecutor, fetch_candidate
from competitor_agent.domain_types import (
    Competitor,
    DimensionType,
    GapStatus,
    InfoGap,
    Observation,
    ResultStatus,
    SourceEvidence,
)
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.interfaces.context import SourceContext
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError


class FakeExtractor:
    """按 URL 返回对应文本（失败 URL 抛 DataSourceUnavailableError）"""

    def fetch(self, gap: InfoGap, context: SourceContext) -> Observation:
        url = str(context.kwargs.get("url"))
        if url == "https://404.com/x":
            raise DataSourceUnavailableError("404")
        text = {
            "https://www.cursor.com/pricing": "Pro plan: $20/month, Premier: $40/month",
            "https://www.cursor.com": "Cursor the AI code editor",
        }.get(url, "")
        ev = SourceEvidence(source_name="web_extractor", url=url, content_hash=str(hash(url)))
        return Observation(gap_field=gap.field, source="web_extractor", raw_text=text, evidence=ev)


class FakeSelector(SourceSelector):
    def __init__(self, candidates):
        self._cands = candidates

    def candidates(self, gap, competitor):
        return self._cands


class RecordingAnalyzer:
    """记录每次分析注入的 AnalysisContext（含 rag_context），返回固定置信度结果"""

    dimension = DimensionType.PRICING

    def __init__(self, confidence: float = 0.9) -> None:
        self.confidence = confidence
        self.calls: list = []

    def analyze(self, observation, gap, context):
        self.calls.append(context)
        return DimensionResult(
            dimension="pricing",
            summary="ok",
            details={"plans": ["Pro"]},
            confidence=self.confidence,
            evidence=[observation.evidence],
            status=ResultStatus.COMPLETE,
        )


class RecordingIngester:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def ingest(self, **kwargs):
        self.calls.append(dict(kwargs))


class FakeRetriever:
    def retrieve(self, query, competitor, dimension, top_k=5):
        return [
            SimpleNamespace(
                competitor=competitor,
                dimension=dimension,
                text="Cursor 官方定价 Pro $20/month（历史片段）",
                source_url="https://www.cursor.com/pricing",
            )
        ]


def _cursor():
    return Competitor(
        name="cursor",
        official_links={"pricing": "https://www.cursor.com/pricing"},
    )


def _execute(executor: GapExecutor, field: str = "pricing") -> tuple[DimensionResult | None, InfoGap]:
    gap = InfoGap(field=field)
    return executor.execute(gap, _cursor()), gap


class TestGapExecutor:
    def test_success_closure(self):
        cand = SourceCandidate(
            source_name="official_pricing", url="https://www.cursor.com/pricing", trust_level=0.9
        )
        executor = GapExecutor(
            selector=FakeSelector([cand]),
            extractor=FakeExtractor(),
            analyzer=RecordingAnalyzer(),
            budget=IterationBudget(max_iterations=5, cost_limit=1.0),
        )
        result, gap = _execute(executor)
        assert result is not None
        assert result.dimension == "pricing"
        assert gap.status in (GapStatus.PARTIAL, GapStatus.CONFIRMED)
        assert gap.evidence
        assert "official_pricing" in gap.sources_tried

    def test_degrades_across_sources(self):
        bad = SourceCandidate(source_name="official_pricing", url="https://404.com/x", trust_level=0.9)
        good = SourceCandidate(source_name="official_home", url="https://www.cursor.com", trust_level=0.9)
        executor = GapExecutor(
            selector=FakeSelector([bad, good]),
            extractor=FakeExtractor(),
            analyzer=RecordingAnalyzer(),
            budget=IterationBudget(max_iterations=5, cost_limit=1.0),
        )
        result, gap = _execute(executor)
        assert result is not None
        assert gap.sources_tried == ["official_pricing", "official_home"]

    def test_budget_exhausted_blocks(self):
        cand = SourceCandidate(
            source_name="official_pricing", url="https://www.cursor.com/pricing", trust_level=0.9
        )
        executor = GapExecutor(
            selector=FakeSelector([cand]),
            extractor=FakeExtractor(),
            analyzer=RecordingAnalyzer(),
            budget=IterationBudget(max_iterations=0, cost_limit=0.0),
        )
        result, gap = _execute(executor)
        assert result is None
        assert gap.status == GapStatus.BLOCKED

    def test_cancelled_session_blocks_without_fetching(self):
        cand = SourceCandidate(
            source_name="official_pricing", url="https://www.cursor.com/pricing", trust_level=0.9
        )
        extractor = FakeExtractor()
        executor = GapExecutor(
            selector=FakeSelector([cand]),
            extractor=extractor,
            analyzer=RecordingAnalyzer(),
            budget=IterationBudget(max_iterations=5, cost_limit=1.0),
            session_id="ex_cancel",
        )
        set_cancel("ex_cancel")
        try:
            result, gap = _execute(executor)
        finally:
            clear_cancel("ex_cancel")
        assert result is None
        assert gap.status == GapStatus.BLOCKED

    def test_rag_context_injected_and_ingested(self):
        cand = SourceCandidate(
            source_name="official_pricing", url="https://www.cursor.com/pricing", trust_level=0.9
        )
        analyzer = RecordingAnalyzer()
        ingester = RecordingIngester()
        executor = GapExecutor(
            selector=FakeSelector([cand]),
            extractor=FakeExtractor(),
            analyzer=analyzer,
            budget=IterationBudget(max_iterations=5, cost_limit=1.0),
            ingester=ingester,
            retriever=FakeRetriever(),
        )
        result, _ = _execute(executor)
        assert result is not None
        assert analyzer.calls, "分析器应被调用"
        assert "cursor" in ingester.calls[0]["competitor"]
        assert ingester.calls[0]["source_url"] == "https://www.cursor.com/pricing"


class TestFetchCandidate:
    def test_dispatches_by_source_name_with_default_fallback(self):
        class TrackingExtractor:
            def __init__(self, name, text):
                self.name = name
                self.text = text
                self.urls: list[str] = []

            def fetch(self, gap, context):
                self.urls.append(str(context.kwargs.get("url")))
                return Observation(
                    gap_field=gap.field,
                    source=self.name,
                    raw_text=self.text,
                    evidence=SourceEvidence(source_name=self.name, url=str(context.kwargs.get("url"))),
                )

        registered = TrackingExtractor("magic", "registered content")
        fallback = TrackingExtractor("default", "fallback content")
        gap = InfoGap(field="pricing")
        c1 = SourceCandidate(source_name="magic", url="https://a.com", trust_level=0.9)
        c2 = SourceCandidate(source_name="other", url="https://b.com", trust_level=0.9)

        obs1 = fetch_candidate(gap, c1, "cursor", fallback, {"magic": registered})
        obs2 = fetch_candidate(gap, c2, "cursor", fallback, {"magic": registered})

        assert obs1.source == "magic"
        assert obs2.source == "default"
        assert registered.urls == ["https://a.com"]
        assert fallback.urls == ["https://b.com"]
