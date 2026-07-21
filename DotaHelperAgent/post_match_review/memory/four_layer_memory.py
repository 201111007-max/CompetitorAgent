"""四层记忆系统统一入口"""
from typing import Any, Dict, List, Optional

from post_match_review.interfaces.memory import IFourLayerMemory
from post_match_review.memory.session_archive import SessionArchive
from post_match_review.memory.persistent_notes import PersistentNotes
from post_match_review.memory.skill_store import SkillStore
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.memory.four_layer")


class FourLayerMemory(IFourLayerMemory):
    """四层记忆系统统一入口"""

    def __init__(
        self,
        session_archive: SessionArchive,
        persistent_notes: PersistentNotes,
        skill_store: SkillStore,
        data_dir: str,
    ) -> None:
        self._session_archive = session_archive
        self._persistent_notes = persistent_notes
        self._skill_store = skill_store
        self._data_dir = data_dir

    async def archive_session(
        self,
        match_id: str,
        report: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Level 1: 归档复盘会话"""
        quality_score = metadata.get("quality_score") if metadata else None
        await self._session_archive.archive(
            match_id=match_id,
            report=report,
            quality_score=quality_score,
            metadata=metadata,
        )
        logger.info(f"会话归档完成: match_id={match_id}")

    async def add_persistent_note(
        self,
        category: str,
        content: str,
        evidence: List[str],
    ) -> None:
        """Level 2: 添加持久笔记"""
        await self._persistent_notes.add_note(
            category=category,
            content=content,
            evidence=evidence,
        )
        logger.info(f"持久笔记添加完成: category={category}")

    async def query_persistent_notes(
        self,
        query: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """检索持久笔记"""
        return await self._persistent_notes.query(query=query, top_k=top_k)

    async def load_skills(self) -> List[Dict[str, Any]]:
        """Level 3: 加载技能
        
        注意: 当前实现为同步操作包装在异步方法中，以保持接口一致性。
        未来如果 SkillStore 支持异步 I/O，可直接替换为异步实现。
        """
        return self._skill_store.list_skills()

    @property
    def session_archive(self) -> SessionArchive:
        """获取会话归档实例"""
        return self._session_archive

    @property
    def persistent_notes(self) -> PersistentNotes:
        """获取持久笔记实例"""
        return self._persistent_notes

    @property
    def skill_store(self) -> SkillStore:
        """获取技能存储实例"""
        return self._skill_store
