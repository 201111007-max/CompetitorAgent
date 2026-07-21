"""技能存储接口定义"""
from typing import Any, Dict, List, Optional, Protocol


class ISkillStore(Protocol):
    """技能存储接口"""

    def save_skill(
        self,
        name: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """保存或更新技能"""
        ...

    def load_skill(self, name: str) -> Optional[Dict[str, Any]]:
        """加载指定技能"""
        ...

    def list_skills(self) -> List[Dict[str, Any]]:
        """列出所有技能"""
        ...

    def check_conflict(
        self,
        name: str,
        content: str,
    ) -> Optional[Dict[str, Any]]:
        """检查与已有技能是否冲突"""
        ...
