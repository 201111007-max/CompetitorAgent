"""Skill 降级框架

提供统一降级处理器和策略枚举，支持链式降级执行。
"""

import logging
from enum import Enum
from typing import Any, Awaitable, Callable, List, Optional, Tuple

from .base import SkillContext, SkillResult

logger = logging.getLogger(__name__)


class FallbackStrategy(Enum):
    """降级策略枚举"""

    RULE_BASED = "rule_based"
    CACHE = "cache"
    DEFAULT = "default"
    CHAIN = "chain"


class FallbackHandler:
    """统一降级处理器"""

    @staticmethod
    async def execute_with_fallback(
        primary: Callable[[Any, Optional[SkillContext]], Awaitable[SkillResult]],
        fallback_chain: List[Tuple[str, Callable[[Any, Optional[SkillContext]], Awaitable[SkillResult]]]],
        input_data: Any,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """执行主逻辑并在失败时按链式降级

        Args:
            primary: 主执行函数
            fallback_chain: 降级函数列表，每项为 (name, func)
            input_data: 输入数据
            context: 执行上下文

        Returns:
            SkillResult 主逻辑或降级结果

        Raises:
            RuntimeError: 当所有降级都失败时抛出
        """
        try:
            return await primary(input_data, context)
        except Exception as e:
            logger.warning(f"Primary execution failed: {e}, trying fallbacks")
            for name, fallback_fn in fallback_chain:
                try:
                    logger.info(f"Trying fallback: {name}")
                    result = await fallback_fn(input_data, context)
                    result.fallback_used = True
                    result.metadata["fallback_name"] = name
                    return result
                except Exception as fe:
                    logger.warning(f"Fallback '{name}' failed: {fe}")
                    continue
            raise RuntimeError("All fallbacks failed")
