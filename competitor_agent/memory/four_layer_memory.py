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
from typing import TYPE_CHECKING

from competitor_agent.interfaces.context import AnalysisSession, Skill
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.memory.evolution_memory import EvolutionMemory
from competitor_agent.memory.persistent_notes import PersistentNotes
from competitor_agent.memory.session_archive import SessionArchive
from competitor_agent.memory.skill_store import SkillStore
from competitor_agent.secret_vault import get_data_dir

if TYPE_CHECKING:
    from competitor_agent.knowledge_base.vector_store import VectorStore

logger = logging.getLogger("competitor_agent.memory.four_layer_memory")


class FourLayerMemory(IFourLayerMemory):
    """组合四层记忆，暴露统一接口"""

    def __init__(
        self,
        data_dir: Path | str | None = None,
        session_ttl_days: int = 30,
        skills_max_per_competitor: int = 50,
        vector_store: VectorStore | None = None,
    ) -> None:
        # 记忆数据根目录（供 facade 注入同根向量层，设计文档 52 §3.1）
        self._data_dir = Path(data_dir) if data_dir else get_data_dir()
        self._sessions = SessionArchive(data_dir, ttl_days=session_ttl_days, vector_store=vector_store)
        self._notes = PersistentNotes(data_dir)
        self._skills = SkillStore(data_dir, max_per_competitor=skills_max_per_competitor)
        self._evolution = EvolutionMemory(data_dir)

    @property
    def data_dir(self) -> Path:
        """记忆数据根目录"""
        return self._data_dir

    def attach_vector_store(self, vector_store: VectorStore) -> None:
        """构造后为 L1 会话归档接入向量召回（设计文档 52：facade enable_rag 时注入）。"""
        self._sessions.attach_vector_store(vector_store)

    # ---- L1 会话归档 ----
    def archive_session(self, session: AnalysisSession) -> None:
        self._sessions.archive(session)

    def list_sessions(self, competitor: str | None = None) -> list[AnalysisSession]:
        """列出归档会话：指定竞品返回该竞品历史，为空返回最近全部。"""
        if competitor:
            return self._sessions.retrieve(competitor)
        return self._sessions.recent_sessions()

    def recent_sessions(self) -> list[AnalysisSession]:
        return self._sessions.recent_sessions()

    def recent_context(self, competitor: str, top_k: int = 5, query: str = "") -> list[str]:
        """L1: 按任务相关度召回可注入的记忆上下文（设计文档 35 §3.2）"""
        return self._sessions.recent_context(competitor, top_k=top_k, query=query)

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

    def record_success(
        self,
        competitor: str,
        gap_field: str,
        source_name: str,
        method: str = "",
    ) -> None:
        self._skills.record_success(competitor, gap_field, source_name, method=method)

    def record_failure(self, competitor: str, gap_field: str, source_name: str) -> None:
        self._skills.record_failure(competitor, gap_field, source_name)

    # ---- L4 进化记录 ----
    def record_outcome(self, source: str, success: bool) -> None:
        self._evolution.record_outcome(source, success)

    def source_success_rates(self) -> dict[str, float]:
        return self._evolution.source_success_rates()

    def top_sources(self, n: int = 5) -> list[tuple[str, float]]:
        return self._evolution.top_sources(n)

    def note_pattern(
        self,
        competitor: str,
        dimension: str,
        pattern: str,
        outcome: str,
    ) -> None:
        self._evolution.note_pattern(competitor, dimension, pattern, outcome)

    def retrieve_patterns(self, competitor: str, dimension: str) -> list[str]:
        return self._evolution.retrieve_patterns(competitor, dimension)

    def retrieve_patterns_with_outcome(
        self, competitor: str, dimension: str
    ) -> list[tuple[str, str]]:
        return self._evolution.retrieve_patterns_with_outcome(competitor, dimension)

    def failure_patterns_for(self, competitor: str) -> list[str]:
        return self._evolution.failure_patterns_for(competitor)