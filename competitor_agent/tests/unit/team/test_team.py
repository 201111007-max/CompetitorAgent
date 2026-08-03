"""team/ 多 Agent 协作流水线测试（M3 3.1/3.2）"""
from competitor_agent.analyzers.registry import AnalyzerRegistry
from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.domain_types import (
    Competitor,
    CompetitorStrategy,
    InfoGap,
    Observation,
    SourceEvidence,
)
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.interfaces.context import SourceContext
from competitor_agent.team.analyzer_agent import AnalyzerAgent
from competitor_agent.team.collector_agent import CollectorAgent
from competitor_agent.team.message_bus import T_COLLECTED, T_DRAFT, MessageBus
from competitor_agent.team.orchestrator import TeamOrchestrator
from competitor_agent.team.validator_agent import FactValidator, ValidatorAgent


class FakeExtractor:
    """按 URL 返回假数据"""

    def fetch(self, gap: InfoGap, context: SourceContext) -> Observation:
        url = str(context.kwargs.get("url"))
        table = {
            "https://www.cursor.com/pricing": "Pro plan: $20/month, Premier: $40/month, Teams: $60/month",
            "https://www.cursor.com": "Cursor the AI code editor, used by teams worldwide",
            "https://docs.cursor.com": "Cursor documentation with feature details",
        }
        text = table.get(url, "")
        ev = SourceEvidence(source_name="web_extractor", url=url, content_hash=SourceEvidence.compute_hash(text))
        return Observation(gap_field=gap.field, source="web_extractor", raw_text=text, evidence=ev)


def _cursor():
    return Competitor(name="cursor", official_links={"pricing": "https://www.cursor.com/pricing"})


def _cursor_strategy():
    return CompetitorStrategy(competitor=_cursor(), gaps=[InfoGap(field="pricing")])


class TestMessageBus:
    def test_publish_distributes_to_subscribers(self):
        bus = MessageBus()
        got = []
        bus.subscribe("t", lambda env: got.append(env.payload))
        bus.publish("t", {"x": 1})
        assert got == [{"x": 1}]

    def test_history_returns_sequenced_envelopes(self):
        bus = MessageBus()
        bus.publish("a", 1)
        bus.publish("b", 2)
        hist = bus.history()
        assert len(hist) == 2
        assert hist[0].sequence == 0 and hist[1].sequence == 1
        assert [e.topic for e in bus.history("b")] == ["b"]

    def test_wildcard_subscription_receives_all(self):
        bus = MessageBus()
        got = []
        bus.subscribe("", lambda env: got.append(env.topic))
        bus.publish("x", 1)
        bus.publish("y", 2)
        assert got == ["x", "y"]


class TestCollectorAgent:
    def test_collect_returns_observations(self):
        bus = MessageBus()
        agent = CollectorAgent(bus, SourceSelector(), FakeExtractor())
        obs = agent.collect(_cursor_strategy())
        assert obs
        assert all(o.gap_field == "pricing" for o in obs)
        assert bus.history(T_COLLECTED)

    def test_failed_sources_are_recorded(self):
        bus = MessageBus()
        selector = SourceSelector()
        agent = CollectorAgent(bus, selector, FakeExtractor())
        strategy = _cursor_strategy()
        agent.collect(strategy)
        assert strategy.gaps[0].sources_tried  # 至少记录尝试过的源


class TestAnalyzerAgent:
    def test_analyze_produces_dimension_results(self):
        bus = MessageBus()
        agent = AnalyzerAgent(bus, AnalyzerRegistry(use_llm=False))
        ev = SourceEvidence(source_name="web_extractor", trust_level=0.9)
        obs = [Observation(gap_field="pricing", source="web_extractor", raw_text="Pro plan $20", evidence=ev)]
        results = agent.analyze("cursor", obs)
        assert results
        assert results[0].dimension == "pricing"
        assert results[0].details.get("plans")  # 规则版识别到 plan


class TestFactValidator:
    def test_missing_evidence_is_intercepted(self):
        v = FactValidator()
        r = DimensionResult(dimension="pricing", summary="X", confidence=0.9)
        outcome = v.validate([r])
        assert not outcome.passed
        assert any(i.kind == "missing_evidence" for i in outcome.issues)

    def test_conflicting_history_is_flagged(self):
        v = FactValidator()
        ev = SourceEvidence(source_name="a", trust_level=0.9)
        current = DimensionResult(dimension="pricing", summary="now", confidence=0.2, evidence=[ev])
        past = DimensionResult(dimension="pricing", summary="past", confidence=0.9, evidence=[ev])
        outcome = v.validate([current], history=[past])
        assert any(i.kind == "conflict" for i in outcome.issues)

    def test_consistent_result_passes(self):
        v = FactValidator()
        ev = SourceEvidence(source_name="a", trust_level=0.9)
        r = DimensionResult(dimension="pricing", summary="X", confidence=0.9, evidence=[ev])
        outcome = v.validate([r])
        assert outcome.passed


class TestTeamOrchestrator:
    def test_full_pipeline_produces_draft(self):
        bus = MessageBus()
        orch = TeamOrchestrator(extractor=FakeExtractor(), bus=bus, use_llm=False)
        report = orch.run("分析 cursor 的定价")
        assert report.competitor.name == "cursor"
        assert report.dimension_results
        assert "## 校验备注" in report.markdown_report or "定价" in report.markdown_report
        assert bus.history(T_DRAFT)

    def test_validator_agent_publishes(self):
        bus = MessageBus()
        agent = ValidatorAgent(bus)
        ev = SourceEvidence(source_name="a", trust_level=0.9)
        r = DimensionResult(dimension="pricing", summary="X", confidence=0.9, evidence=[ev])
        outcome = agent.validate("cursor", [r])
        assert outcome.passed
        assert len(bus.history("validated")) == 1
