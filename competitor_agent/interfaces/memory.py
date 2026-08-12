"""四层记忆契约"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from competitor_agent.interfaces.context import AnalysisSession, Skill


@runtime_checkable
class IFourLayerMemory(Protocol):
    """L1 会话归档 / L2 持久笔记 / L3 技能 / L4 进化记录"""

    def archive_session(self, session: AnalysisSession) -> None:
        """L1: 归档一次分析会话"""
        ...

    def list_sessions(self, competitor: str | None = None) -> list[AnalysisSession]:
        """L1: 列出归档会话；competitor 为空返回最近全部"""
        ...

    def save_note(self, competitor: str, note: str) -> None:
        """L2: 保存持久笔记"""
        ...

    def retrieve_notes(self, competitor: str) -> list[str]:
        """L2: 取回笔记"""
        ...

    def record_skill(self, skill: Skill) -> None:
        """L3: 沉淀技能"""
        ...

    def retrieve_skills(self, competitor: str) -> list[Skill]:
        """L3: 取回技能"""
        ...

    def record_outcome(self, source: str, success: bool) -> None:
        """L4: 记录数据源成功率"""
        ...

    def source_success_rates(self) -> dict[str, float]:
        """L4: 数据源成功率统计"""
        ...


__all__ = ["IFourLayerMemory"]
