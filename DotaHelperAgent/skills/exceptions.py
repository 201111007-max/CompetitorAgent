"""Skill 异常体系

定义 Skill 模块中使用的基础异常类型，便于统一错误处理。
"""

from typing import Optional


class SkillException(Exception):
    """Skill 基础异常"""

    def __init__(self, message: str, skill_name: Optional[str] = None) -> None:
        self.skill_name = skill_name
        super().__init__(message)


class SkillExecutionError(SkillException):
    """Skill 执行错误"""

    def __init__(self, message: str, skill_name: Optional[str] = None) -> None:
        super().__init__(message, skill_name=skill_name)


class SkillTimeoutError(SkillException):
    """Skill 执行超时"""

    def __init__(self, message: str, skill_name: Optional[str] = None) -> None:
        super().__init__(message, skill_name=skill_name)


class SkillFallbackError(SkillException):
    """Skill 降级策略也失败"""

    def __init__(self, message: str, skill_name: Optional[str] = None) -> None:
        super().__init__(message, skill_name=skill_name)
