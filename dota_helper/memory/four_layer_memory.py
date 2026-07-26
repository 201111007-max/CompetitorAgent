"""四层记忆系统统一入口"""
import asyncio
from typing import Any, Dict, List, Optional

from dota_helper.interfaces.memory import IFourLayerMemory
from dota_helper.memory.session_archive import SessionArchive
from dota_helper.memory.persistent_notes import PersistentNotes
from dota_helper.memory.skill_store import SkillStore
from dota_helper.observability.logger import get_logger

logger = get_logger("memory.four_layer")


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

        P3-3: 使用 asyncio.to_thread 包装同步 I/O 为真异步。
        """
        return await asyncio.to_thread(self._skill_store.list_skills)

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
