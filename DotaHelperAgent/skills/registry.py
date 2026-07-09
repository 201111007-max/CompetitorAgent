"""Skill 注册表

提供全局单例的 Skill 注册、发现和调用入口。
"""

import logging
from typing import Any, Dict, List, Optional

from .base import BaseSkill, SkillContext, SkillResult
from .exceptions import SkillExecutionError

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Skill 注册表（单例）"""

    _instance: Optional['SkillRegistry'] = None

    def __new__(cls) -> 'SkillRegistry':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._skills: Dict[str, BaseSkill] = {}
        self._initialized = True

    def register(self, skill: BaseSkill) -> None:
        """注册 Skill

        Args:
            skill: Skill 实例

        Raises:
            ValueError: Skill 名称已存在
        """
        if skill.name in self._skills:
            raise ValueError(f"Skill '{skill.name}' already registered")
        self._skills[skill.name] = skill
        logger.info(f"Registered skill: {skill.name} v{skill.version}")

    def unregister(self, name: str) -> None:
        """注销 Skill

        Args:
            name: Skill 名称
        """
        if name in self._skills:
            del self._skills[name]
            logger.info(f"Unregistered skill: {name}")

    def get(self, name: str) -> Optional[BaseSkill]:
        """获取 Skill

        Args:
            name: Skill 名称

        Returns:
            Skill 实例或 None
        """
        return self._skills.get(name)

    def list_all(self) -> List[str]:
        """列出所有已注册 Skill 名称"""
        return list(self._skills.keys())

    def get_info(self, name: str) -> Optional[Dict[str, Any]]:
        """获取 Skill 元信息"""
        skill = self.get(name)
        if skill is None:
            return None
        return {
            "name": skill.name,
            "version": skill.version,
            "description": skill.description,
            "enabled": skill.enabled,
            "timeout": skill.timeout,
        }

    async def invoke(
        self,
        name: str,
        input_data: Any,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """调用指定 Skill

        Args:
            name: Skill 名称
            input_data: 输入数据
            context: 执行上下文

        Returns:
            SkillResult 执行结果

        Raises:
            SkillExecutionError: Skill 不存在或被禁用
        """
        skill = self.get(name)
        if skill is None:
            raise SkillExecutionError(f"Skill '{name}' not found", skill_name=name)
        if not skill.enabled:
            raise SkillExecutionError(f"Skill '{name}' is disabled", skill_name=name)
        return await skill.run(input_data, context)


def get_registry() -> SkillRegistry:
    """获取 SkillRegistry 单例"""
    return SkillRegistry()
