"""interfaces 契约冒烟测试：所有 Protocol 可被 fake 实现满足（运行时类型可检查）"""
from competitor_agent.domain_types import (
    Competitor,
    CompetitorStrategy,
    DimensionResult,
    DimensionType,
    InfoGap,
    Observation,
)
from competitor_agent.interfaces import (
    AnalysisContext,
    AnalysisSession,
    BudgetState,
    ICompetitorAnalyzer,
    ICompetitorDataSource,
    IFourLayerMemory,
    IReportBuilder,
    IStopVerifier,
    IStrategicPlanner,
    Skill,
    SourceContext,
    StopDecision,
)


class FakeDataSource:
    source_name = "fake_source"

    def is_available(self) -> bool:
        return True

    def fetch(self, gap: InfoGap, context: SourceContext) -> Observation:
        return Observation(gap_field=gap.field, source=self.source_name, raw_text="data")


class FakeAnalyzer:
    dimension = DimensionType.PRICING

    def analyze(self, observation, gap, context):
        return DimensionResult(dimension="pricing", summary="ok", confidence=0.9)

    def confidence(self, result: DimensionResult) -> float:
        return result.confidence


class FakePlanner:
    def plan(self, task, memory) -> CompetitorStrategy:
        return CompetitorStrategy(competitor=Competitor(name="default"))


class FakeMemory:
    def archive_session(self, session: AnalysisSession) -> None: ...
    def save_note(self, competitor: str, note: str) -> None: ...
    def retrieve_notes(self, competitor: str) -> list: ...
    def record_skill(self, skill: Skill) -> None: ...
    def retrieve_skills(self, competitor: str) -> list: ...
    def record_outcome(self, source: str, success: bool) -> None: ...
    def source_success_rates(self) -> dict: ...


class FakeVerifier:
    def verify(self, gaps, budget_state: BudgetState) -> StopDecision:
        return StopDecision(should_stop=False)


class FakeReporter:
    def build(self, competitor, results, gaps_pending, terminal_state):
        return None

    def to_markdown(self, report) -> str:
        return "# report"


class TestProtocolRuntimeCheck:
    def test_data_source_isinstance(self):
        assert isinstance(FakeDataSource(), ICompetitorDataSource)

    def test_analyzer_isinstance(self):
        assert isinstance(FakeAnalyzer(), ICompetitorAnalyzer)

    def test_planner_isinstance(self):
        assert isinstance(FakePlanner(), IStrategicPlanner)

    def test_memory_isinstance(self):
        assert isinstance(FakeMemory(), IFourLayerMemory)

    def test_verifier_isinstance(self):
        assert isinstance(FakeVerifier(), IStopVerifier)

    def test_reporter_isinstance(self):
        assert isinstance(FakeReporter(), IReportBuilder)


class TestProtocolBehavior:
    def test_fake_data_source_fetch(self):
        ds = FakeDataSource()
        obs = ds.fetch(InfoGap(field="pricing"), SourceContext(competitor_name="cursor"))
        assert obs.source == "fake_source"
        assert obs.gap_field == "pricing"

    def test_fake_analyzer_confidence(self):
        result = FakeAnalyzer().analyze(Observation(gap_field="pricing", source="s", raw_text=""), InfoGap(field="pricing"), AnalysisContext())
        assert FakeAnalyzer().confidence(result) == 0.9