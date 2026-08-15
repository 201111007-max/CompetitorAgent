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

    def recent_context(self, competitor: str, top_k: int = 5, query: str = "") -> list[str]:
        """L1: 按任务相关度召回可注入的记忆上下文（摘要 + 最近相关会话，设计文档 35）"""
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

    def record_success(
        self,
        competitor: str,
        gap_field: str,
        source_name: str,
        method: str = "",
    ) -> None:
        """L3: 分析成功后自动提炼技能（可携带成功做法 method，设计文档 35）"""
        ...

    def record_outcome(self, source: str, success: bool) -> None:
        """L4: 记录数据源成功率"""
        ...

    def source_success_rates(self) -> dict[str, float]:
        """L4: 数据源成功率统计"""
        ...

    def note_pattern(
        self,
        competitor: str,
        dimension: str,
        pattern: str,
        outcome: str,
    ) -> None:
        """L4: 记录可检索经验/反例（outcome ∈ success/degraded/failure，设计文档 35）"""
        ...

    def retrieve_patterns(self, competitor: str, dimension: str) -> list[str]:
        """L4: 取回某竞品某维度的经验/反例（供规划与失败归因联动）"""
        ...

    def retrieve_patterns_with_outcome(
        self, competitor: str, dimension: str
    ) -> list[tuple[str, str]]:
        """L4: 取回某竞品某维度的 (pattern, outcome) 列表（设计文档 45，供规划提权/降权）"""
        ...

    def failure_patterns_for(self, competitor: str) -> list[str]:
        """L4: 取回某竞品失败/降级反例涉及的源名清单（设计文档 45，供源选择降级）"""
        ...


__all__ = ["IFourLayerMemory"]
