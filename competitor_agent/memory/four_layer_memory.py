"""四层记忆统一实现（FourLayerMemory）

L1 SessionArchive（会话归档）
L2 PersistentNotes（持久笔记）
L3 SkillStore（技能沉淀）
L4 EvolutionMemory（进化记录）

实现 IFourLayerMemory 契约，供 strategic_loop / SourceSelector 消费。
所有层共享同一 data_dir，默认 ``<data_dir>/memory/``。
"""
from __future__ import annotations

import logging
from pathlib import Path

from competitor_agent.interfaces.context import AnalysisSession, Skill
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.memory.evolution_memory import EvolutionMemory
from competitor_agent.memory.persistent_notes import PersistentNotes
from competitor_agent.memory.session_archive import SessionArchive
from competitor_agent.memory.skill_store import SkillStore

logger = logging.getLogger("competitor_agent.memory.four_layer_memory")


class FourLayerMemory(IFourLayerMemory):
    """组合四层记忆，暴露统一接口"""

    def __init__(
        self,
        data_dir: Path | str | None = None,
        session_ttl_days: int = 30,
        skills_max_per_competitor: int = 50,
    ) -> None:
        self._sessions = SessionArchive(data_dir, ttl_days=session_ttl_days)
        self._notes = PersistentNotes(data_dir)
        self._skills = SkillStore(data_dir, max_per_competitor=skills_max_per_competitor)
        self._evolution = EvolutionMemory(data_dir)

    # ---- L1 会话归档 ----
    def archive_session(self, session: AnalysisSession) -> None:
        self._sessions.archive(session)

    def recent_sessions(self) -> list[AnalysisSession]:
        return self._sessions.recent_sessions()

    # ---- L2 持久笔记 ----
    def save_note(self, competitor: str, note: str) -> None:
        self._notes.save_note(competitor, note)

    def retrieve_notes(self, competitor: str) -> list[str]:
        return self._notes.retrieve_notes(competitor)

    # ---- L3 技能 ----
    def record_skill(self, skill: Skill) -> None:
        self._skills.record_skill(skill)

    def retrieve_skills(self, competitor: str) -> list[Skill]:
        return self._skills.retrieve_skills(competitor)

    def record_success(self, competitor: str, gap_field: str, source_name: str) -> None:
        self._skills.record_success(competitor, gap_field, source_name)

    def record_failure(self, competitor: str, gap_field: str, source_name: str) -> None:
        self._skills.record_failure(competitor, gap_field, source_name)

    # ---- L4 进化记录 ----
    def record_outcome(self, source: str, success: bool) -> None:
        self._evolution.record_outcome(source, success)

    def source_success_rates(self) -> dict[str, float]:
        return self._evolution.source_success_rates()

    def top_sources(self, n: int = 5) -> list[tuple[str, float]]:
        return self._evolution.top_sources(n)