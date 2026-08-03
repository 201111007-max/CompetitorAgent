"""domain_types 数据模型单测：构造、序列化、状态机"""

from competitor_agent.domain_types import (
    ComparisonReport,
    Competitor,
    CompetitorReport,
    CompetitorStrategy,
    DimensionResult,
    DimensionType,
    GapStatus,
    InfoGap,
    Observation,
    ObservationStatus,
    ProgressEvent,
    ResultStatus,
    SourceEvidence,
    TerminalState,
)


class TestCompetitor:
    def test_name_normalized(self):
        c = Competitor(name="Claude Code", aliases=["claude-code", "claude"])
        assert c.name == "claude-code"
        assert c.category == "ai_coding_agent"
        assert c.official_links == {}

    def test_aliases_and_links(self):
        c = Competitor(
            name="cursor",
            aliases=["anysphere"],
            official_links={"pricing": "https://cursor.com/pricing"},
        )
        assert c.aliases == ["anysphere"]
        assert c.official_links["pricing"] == "https://cursor.com/pricing"


class TestSourceEvidence:
    def test_compute_hash_deterministic(self):
        h1 = SourceEvidence.compute_hash("hello")
        h2 = SourceEvidence.compute_hash("hello")
        assert h1 == h2
        assert len(h1) == 16

    def test_compute_hash_differs(self):
        assert SourceEvidence.compute_hash("a") != SourceEvidence.compute_hash("b")

    def test_access_time_auto(self):
        ev = SourceEvidence(source_name="docs")
        assert ev.access_time
        assert ev.trust_level == 0.5


class TestObservation:
    def test_construct_and_to_dict(self):
        ev = SourceEvidence(source_name="pricing_page", url="https://x.com/pricing")
        obs = Observation(
            gap_field="pricing",
            source="pricing_page",
            raw_text="Pro $20/mo",
            extracted={"price": "$20/mo"},
            evidence=ev,
            status=ObservationStatus.OK,
        )
        d = obs.to_dict()
        assert d["gap_field"] == "pricing"
        assert d["extracted"]["price"] == "$20/mo"
        assert d["evidence"]["source_name"] == "pricing_page"
        assert d["status"] == "ok"

    def test_from_json_roundtrip(self):
        ev = SourceEvidence(source_name="docs", url="https://x.com")
        obs = Observation(
            gap_field="features",
            source="docs",
            raw_text="support tool X",
            extracted={"features": ["x"]},
            evidence=ev,
        )
        restored = Observation.from_json(obs.to_dict())
        assert restored.gap_field == "features"
        assert restored.evidence.url == "https://x.com"
        assert restored.status == ObservationStatus.OK

    def test_default_status(self):
        obs = Observation(gap_field="pricing", source="s", raw_text="")
        assert obs.status == ObservationStatus.OK


class TestInfoGap:
    def test_defaults(self):
        gap = InfoGap(field="pricing")
        assert gap.priority == 5
        assert gap.confidence == 0.0
        assert gap.status == GapStatus.OPEN
        assert gap.evidence == []

    def test_is_core_and_satisfied(self):
        gap = InfoGap(field="pricing", priority=9, confidence=0.85)
        assert gap.is_core
        assert gap.is_satisfied
        assert not gap.is_closed

    def test_is_closed_for_confirmed(self):
        gap = InfoGap(field="features", status=GapStatus.CONFIRMED)
        assert gap.is_closed

    def test_add_evidence_dedup(self):
        gap = InfoGap(field="pricing")
        ev = SourceEvidence(source_name="s", content_hash="h1")
        gap.add_evidence(ev)
        gap.add_evidence(SourceEvidence(source_name="s", content_hash="h1"))
        assert len(gap.evidence) == 1

    def test_record_source_try_dedup(self):
        gap = InfoGap(field="pricing")
        gap.record_source_try("docs")
        gap.record_source_try("docs")
        gap.record_source_try("pricing_page")
        assert gap.sources_tried == ["docs", "pricing_page"]

    def test_to_dict(self):
        gap = InfoGap(field="pricing", priority=8, confidence=0.5)
        d = gap.to_dict()
        assert d["field"] == "pricing"
        assert d["priority"] == 8
        assert d["status"] == "open"
        assert d["evidence_count"] == 0


class TestStrategy:
    def test_defaults(self):
        s = CompetitorStrategy(competitor=Competitor(name="cursor"))
        assert s.gaps == []
        assert s.terminal_thresholds["confidence"] == 0.8

    def test_budget_allocation(self):
        s = CompetitorStrategy(
            competitor=Competitor(name="cursor"),
            budget_allocation={DimensionType.PRICING: 3},
        )
        assert s.budget_allocation[DimensionType.PRICING] == 3


class TestReport:
    def test_dimension_result_defaults(self):
        r = DimensionResult(dimension="pricing")
        assert r.status == ResultStatus.PARTIAL
        assert r.timestamp
        assert r.evidence == []

    def test_competitor_report(self):
        report = CompetitorReport(competitor=Competitor(name="cursor"))
        assert report.overall_confidence == 0.0
        assert report.gaps_pending == []
        assert report.created_at

    def test_comparison_report(self):
        r = ComparisonReport(
            competitors=[Competitor(name="a"), Competitor(name="b")],
            reports=[
                CompetitorReport(competitor=Competitor(name="a")),
                CompetitorReport(competitor=Competitor(name="b")),
            ],
        )
        assert len(r.competitors) == 2
        assert len(r.reports) == 2


class TestEvents:
    def test_progress_event_to_dict(self):
        e = ProgressEvent(event="phase_start", phase="strategic", progress=0.1, message="start")
        d = e.to_dict()
        assert d["event"] == "phase_start"
        assert d["phase"] == "strategic"

    def test_progress_event_sse(self):
        e = ProgressEvent(event="progress", progress=0.5, message="hi")
        s = e.to_sse()
        assert s.startswith("data: ")
        assert s.endswith("\n\n")
        assert "hi" in s


class TestEnums:
    def test_dimension_values(self):
        assert DimensionType.PRICING.value == "pricing"
        assert DimensionType.FEATURE.value == "feature"

    def test_gap_status_values(self):
        assert GapStatus.CONFIRMED.value == "confirmed"
        assert GapStatus.CLOSED.value == "closed"

    def test_terminal_state_values(self):
        assert TerminalState.PARTIAL.value == "partial"
