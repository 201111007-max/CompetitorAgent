"""Skill 抽象基类

定义所有 Skill 必须实现的接口、执行结果结构和执行上下文。
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .exceptions import SkillExecutionError

logger = logging.getLogger(__name__)


@dataclass
class SkillContext:
    """Skill 执行上下文"""

    session_id: Optional[str] = None
    user_id: Optional[str] = None
    trace_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "trace_id": self.trace_id,
            "metadata": self.metadata,
        }


@dataclass
class SkillResult:
    """Skill 执行结果"""

    success: bool
    data: Any
    error: Optional[str] = None
    confidence: float = 1.0
    execution_time: float = 0.0
    fallback_used: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "confidence": self.confidence,
            "execution_time": self.execution_time,
            "fallback_used": self.fallback_used,
            "metadata": self.metadata,
        }


class BaseSkill(ABC):
    """Skill 抽象基类

    所有具体 Skill 必须继承此类并实现 execute 和 _fallback 方法。
    """

    def __init__(
        self,
        name: str,
        version: str = "1.0.0",
        description: str = "",
        timeout: float = 30.0,
    ) -> None:
        self.name = name
        self.version = version
        self.description = description
        self.timeout = timeout
        self._enabled = True

    @abstractmethod
    async def execute(
        self,
        input_data: Any,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """执行 Skill 主逻辑

        Args:
            input_data: Skill 输入数据
            context: 执行上下文

        Returns:
            SkillResult 执行结果
        """
        pass

    @abstractmethod
    async def _fallback(
        self,
        input_data: Any,
        context: Optional[SkillContext] = None,
        error: Optional[Exception] = None,
    ) -> SkillResult:
        """降级方案

        Args:
            input_data: Skill 输入数据
            context: 执行上下文
            error: 触发了降级的异常

        Returns:
            SkillResult 降级结果
        """
        pass

    async def run(
        self,
        input_data: Any,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """执行入口（带降级和超时）

        Args:
            input_data: Skill 输入数据
            context: 执行上下文

        Returns:
            SkillResult 执行或降级结果
        """
        context = context or SkillContext()
        start_time = time.time()

        try:
            result = await asyncio.wait_for(
                self.execute(input_data, context),
                timeout=self.timeout,
            )
            result.execution_time = time.time() - start_time
            return result
        except Exception as e:
            logger.warning(
                f"Skill '{self.name}' execution failed: {e}, "
                f"falling back to rule-based approach"
            )
            try:
                fallback_result = await self._fallback(input_data, context, e)
                fallback_result.execution_time = time.time() - start_time
                fallback_result.fallback_used = True
                fallback_result.metadata["fallback_error"] = str(e)
                return fallback_result
            except Exception as fallback_error:
                raise SkillExecutionError(
                    f"Both main and fallback failed for skill '{self.name}': {fallback_error}",
                    skill_name=self.name,
                ) from fallback_error

    def enable(self) -> None:
        """启用 Skill"""
        self._enabled = True

    def disable(self) -> None:
        """禁用 Skill"""
        self._enabled = False

    @property
    def enabled(self) -> bool:
        """是否启用"""
        return self._enabled
