"""Skill 模块

将轻量、单次 LLM 调用的产品功能封装为可复用的 Skill 单元。
"""

from .base import BaseSkill, SkillContext, SkillResult
from .registry import SkillRegistry, get_registry
from .exceptions import (
    SkillException,
    SkillExecutionError,
    SkillTimeoutError,
    SkillFallbackError,
)
from .fallback import FallbackHandler, FallbackStrategy

__all__ = [
    "BaseSkill",
    "SkillContext",
    "SkillResult",
    "SkillRegistry",
    "get_registry",
    "SkillException",
    "SkillExecutionError",
    "SkillTimeoutError",
    "SkillFallbackError",
    "FallbackHandler",
    "FallbackStrategy",
]
