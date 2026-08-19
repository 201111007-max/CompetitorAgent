"""interfaces 契约冒烟测试：存活 Protocol 可被 fake 实现满足（运行时类型可检查）

设计文档 49：planner/verifier/analyzer/collector 协议已随规则管线删除，
仅保留记忆（IFourLayerMemory）与报告（IReportBuilder）契约。
"""
from __future__ import annotations

from competitor_agent.interfaces import (
    AnalysisSession,
    IFourLayerMemory,
    IReportBuilder,
    Skill,
)


class FakeMemory:
    def archive_session(self, session: AnalysisSession) -> None:
        return None

    def list_sessions(self, competitor: str | None = None) -> list:
        return []

    def recent_context(self, competitor: str, top_k: int = 5, query: str = "") -> list:
        return []

    def save_note(self, competitor: str, note: str) -> None:
        return None

    def retrieve_notes(self, competitor: str) -> list:
        return []

    def record_skill(self, skill: Skill) -> None:
        return None

    def retrieve_skills(self, competitor: str) -> list:
        return []

    def record_success(self, competitor: str, gap_field: str, source_name: str, method: str = "") -> None:
        return None

    def record_outcome(self, source: str, success: bool) -> None:
        return None

    def source_success_rates(self) -> dict:
        return {}

    def note_pattern(self, competitor: str, dimension: str, pattern: str, outcome: str) -> None:
        return None

    def retrieve_patterns(self, competitor: str, dimension: str) -> list:
        return []

    def retrieve_patterns_with_outcome(self, competitor: str, dimension: str) -> list:
        return []

    def failure_patterns_for(self, competitor: str) -> list:
        return []


class FakeReporter:
    def build(self, competitor, results, gaps_pending, terminal_state):
        return None

    def to_markdown(self, report) -> str:
        return "# report"


class TestProtocolRuntimeCheck:
    def test_memory_isinstance(self):
        assert isinstance(FakeMemory(), IFourLayerMemory)

    def test_reporter_isinstance(self):
        assert isinstance(FakeReporter(), IReportBuilder)


class TestProtocolBehavior:
    def test_fake_memory_skills(self):
        memory = FakeMemory()
        memory.record_skill(
            Skill(competitor_name="cursor", gap_field="pricing", source_name="official", method="直接抓官方定价页")
        )
        assert memory.retrieve_skills("cursor") == []

    def test_fake_reporter_markdown(self):
        assert FakeReporter().to_markdown(None) == "# report"
