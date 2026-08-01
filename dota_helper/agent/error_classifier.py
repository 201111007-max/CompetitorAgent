"""错误分类器 — 将异常按可恢复性分级

分类体系：
- RECOVERABLE: 瞬时故障，重试可恢复（网络超时、LLM 限流、MCP 超时）
- DEGRADABLE: 局部故障，跳过当前操作可继续（工具不存在、参数错误、连接丢失）
- TERMINAL: 致命故障，必须终止（API Key 无效、系统错误）
- UNKNOWN: 无法分类，降级为纯 Thought 继续
"""
from enum import Enum
from typing import Optional

from dota_helper.mcp_client.types import MCPConnectionError
from dota_helper.observability.logger import get_logger

logger = get_logger("agent.error_classifier")


class ErrorCategory(Enum):
    """错误分类"""
    RECOVERABLE = "recoverable"   # 可恢复，重试
    DEGRADABLE = "degradable"     # 可降级，跳过当前操作
    TERMINAL = "terminal"         # 致命，终止循环
    UNKNOWN = "unknown"           # 未知，降级为 Thought


class ClassifiedError:
    """分类后的错误信息

    Attributes:
        category: 错误分类
        message: 用户友好的错误描述
        retryable: 是否可重试
        detail: 原始错误详情（日志用）
    """

    def __init__(
        self,
        category: ErrorCategory,
        message: str,
        retryable: bool = False,
        detail: str = "",
    ) -> None:
        self.category = category
        self.message = message
        self.retryable = retryable
        self.detail = detail

    def __repr__(self) -> str:
        return f"ClassifiedError({self.category.value}): {self.message}"


class ErrorClassifier:
    """异常分类器

    根据异常类型和内容，将异常映射到 ErrorCategory。
    """

    # LLM 限流/服务端错误关键词
    _LLM_RETRYABLE_KEYWORDS = [
        "429", "rate limit", "too many requests", "quota exceeded",
        "503", "service unavailable", "temporarily unavailable",
        "502", "bad gateway", "504", "gateway timeout",
        "timeout", "timed out", "connection reset",
    ]

    # 致命错误关键词
    _LLM_TERMINAL_KEYWORDS = [
        "401", "unauthorized", "403", "forbidden",
        "invalid api key", "authentication", "no api key",
        "insufficient_quota", "billing",
    ]

    def classify(self, error: Exception, context: Optional[str] = None) -> ClassifiedError:
        """对异常进行分类

        Args:
            error: 原始异常
            context: 可选的上下文信息（如工具名）

        Returns:
            ClassifiedError: 分类后的错误
        """
        error_str = str(error).lower()
        error_type = type(error).__name__

        # ── MCP 连接错误 ──
        if isinstance(error, MCPConnectionError):
            if error.reason == MCPConnectionError.TIMEOUT:
                return ClassifiedError(
                    category=ErrorCategory.RECOVERABLE,
                    message=f"工具调用超时{' (' + context + ')' if context else ''}，正在重试...",
                    retryable=True,
                    detail=str(error),
                )
            if error.reason == MCPConnectionError.CONNECTION_LOST:
                return ClassifiedError(
                    category=ErrorCategory.DEGRADABLE,
                    message=f"MCP 连接断开{' (' + context + ')' if context else ''}，跳过当前工具调用",
                    retryable=False,
                    detail=str(error),
                )
            if error.reason == MCPConnectionError.STARTUP_FAILED:
                return ClassifiedError(
                    category=ErrorCategory.DEGRADABLE,
                    message="MCP Server 启动失败，工具不可用",
                    retryable=False,
                    detail=str(error),
                )
            if error.reason == MCPConnectionError.SDK_UNAVAILABLE:
                return ClassifiedError(
                    category=ErrorCategory.DEGRADABLE,
                    message="MCP SDK 不可用，工具不可用",
                    retryable=False,
                    detail=str(error),
                )
            return ClassifiedError(
                category=ErrorCategory.DEGRADABLE,
                message=f"MCP 连接错误{' (' + context + ')' if context else ''}",
                retryable=False,
                detail=str(error),
            )

        # ── asyncio.TimeoutError ──
        if isinstance(error, TimeoutError):
            return ClassifiedError(
                category=ErrorCategory.RECOVERABLE,
                message=f"操作超时{' (' + context + ')' if context else ''}，正在重试...",
                retryable=True,
                detail=str(error),
            )

        # ── ValueError（工具不存在、参数错误） ──
        if isinstance(error, ValueError):
            return ClassifiedError(
                category=ErrorCategory.DEGRADABLE,
                message=f"工具调用参数错误: {error}",
                retryable=False,
                detail=str(error),
            )

        # ── RuntimeError（MCP 未初始化等） ──
        if isinstance(error, RuntimeError):
            return ClassifiedError(
                category=ErrorCategory.DEGRADABLE,
                message=f"运行时错误: {error}",
                retryable=False,
                detail=str(error),
            )

        # ── LLM 相关错误（通过字符串匹配） ──
        if any(kw in error_str for kw in self._LLM_TERMINAL_KEYWORDS):
            return ClassifiedError(
                category=ErrorCategory.TERMINAL,
                message=f"LLM 服务认证失败: {error}",
                retryable=False,
                detail=str(error),
            )

        if any(kw in error_str for kw in self._LLM_RETRYABLE_KEYWORDS):
            return ClassifiedError(
                category=ErrorCategory.RECOVERABLE,
                message=f"LLM 服务暂时不可用，正在重试...",
                retryable=True,
                detail=str(error),
            )

        # ── 未知错误 ──
        logger.warning("未分类的异常: type=%s, error=%s", error_type, str(error))
        return ClassifiedError(
            category=ErrorCategory.UNKNOWN,
            message=f"发生未知错误: {error}",
            retryable=False,
            detail=str(error),
        )
