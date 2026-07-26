"""四层记忆系统接口定义"""
from typing import Any, Dict, List, Optional, Protocol


class IFourLayerMemory(Protocol):
    """四层记忆系统接口"""

    async def archive_session(
        self,
        match_id: str,
        report: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Level 1: 归档复盘会话"""
        ...

    async def add_persistent_note(
        self,
        category: str,
        content: str,
        evidence: List[str],
    ) -> None:
        """Level 2: 添加持久笔记"""
        ...

    async def query_persistent_notes(
        self,
        query: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """检索持久笔记"""
        ...

    async def load_skills(self) -> List[Dict[str, Any]]:
        """Level 3: 加载所有技能"""
        ...
