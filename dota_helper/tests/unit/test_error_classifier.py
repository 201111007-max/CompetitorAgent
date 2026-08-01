"""错误分类器单元测试"""
import asyncio

import pytest

from dota_helper.agent.error_classifier import ErrorClassifier, ErrorCategory, ClassifiedError
from dota_helper.mcp_client.types import MCPConnectionError


class TestErrorClassifier:
    """测试 ErrorClassifier 的异常分类逻辑"""

    def setup_method(self) -> None:
        self.classifier = ErrorClassifier()

    # ── MCPConnectionError ──

    def test_mcp_timeout_is_recoverable(self) -> None:
        """MCP 超时 → RECOVERABLE"""
        error = MCPConnectionError(MCPConnectionError.TIMEOUT, "timeout after 30s")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.RECOVERABLE
        assert result.retryable is True

    def test_mcp_connection_lost_is_degradable(self) -> None:
        """MCP 连接断开 → DEGRADABLE"""
        error = MCPConnectionError(MCPConnectionError.CONNECTION_LOST, "connection reset")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.DEGRADABLE
        assert result.retryable is False

    def test_mcp_startup_failed_is_degradable(self) -> None:
        """MCP 启动失败 → DEGRADABLE"""
        error = MCPConnectionError(MCPConnectionError.STARTUP_FAILED, "server crashed")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.DEGRADABLE

    def test_mcp_sdk_unavailable_is_degradable(self) -> None:
        """MCP SDK 不可用 → DEGRADABLE"""
        error = MCPConnectionError(MCPConnectionError.SDK_UNAVAILABLE, "mcp not installed")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.DEGRADABLE

    # ── TimeoutError ──

    def test_asyncio_timeout_is_recoverable(self) -> None:
        """asyncio.TimeoutError → RECOVERABLE"""
        error = asyncio.TimeoutError("operation timed out")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.RECOVERABLE
        assert result.retryable is True

    def test_builtin_timeout_is_recoverable(self) -> None:
        """内置 TimeoutError → RECOVERABLE"""
        error = TimeoutError("timed out")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.RECOVERABLE

    # ── ValueError / RuntimeError ──

    def test_value_error_is_degradable(self) -> None:
        """ValueError → DEGRADABLE"""
        error = ValueError("工具 'xxx' 不在可用工具列表中")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.DEGRADABLE

    def test_runtime_error_is_degradable(self) -> None:
        """RuntimeError → DEGRADABLE"""
        error = RuntimeError("MCP Client 未连接")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.DEGRADABLE

    # ── LLM 认证错误 → TERMINAL ──

    def test_401_is_terminal(self) -> None:
        """401 Unauthorized → TERMINAL"""
        error = Exception("401 Unauthorized: invalid API key")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.TERMINAL

    def test_403_is_terminal(self) -> None:
        """403 Forbidden → TERMINAL"""
        error = Exception("403 Forbidden: access denied")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.TERMINAL

    def test_invalid_api_key_is_terminal(self) -> None:
        """invalid api key → TERMINAL"""
        error = Exception("Invalid API key provided")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.TERMINAL

    def test_insufficient_quota_is_terminal(self) -> None:
        """insufficient_quota → TERMINAL"""
        error = Exception("insufficient_quota: billing required")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.TERMINAL

    # ── LLM 限流/服务端错误 → RECOVERABLE ──

    def test_429_is_recoverable(self) -> None:
        """429 Too Many Requests → RECOVERABLE"""
        error = Exception("429 Too Many Requests: rate limit exceeded")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.RECOVERABLE
        assert result.retryable is True

    def test_503_is_recoverable(self) -> None:
        """503 Service Unavailable → RECOVERABLE"""
        error = Exception("503 Service Unavailable")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.RECOVERABLE

    def test_timeout_keyword_is_recoverable(self) -> None:
        """timeout 关键词 → RECOVERABLE"""
        error = Exception("HTTPSConnectionPool: Read timed out")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.RECOVERABLE

    # ── 未知错误 → UNKNOWN ──

    def test_unknown_error_is_unknown(self) -> None:
        """无法分类的异常 → UNKNOWN"""
        error = Exception("some weird error that doesn't match any pattern")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.UNKNOWN
        assert result.retryable is False

    def test_type_error_is_unknown(self) -> None:
        """TypeError → UNKNOWN"""
        error = TypeError("unsupported operand type(s)")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.UNKNOWN

    # ── 带上下文参数 ──

    def test_classify_with_context(self) -> None:
        """传入 context 参数时，消息中包含工具名"""
        error = MCPConnectionError(MCPConnectionError.TIMEOUT, "timeout")
        result = self.classifier.classify(error, context="get_match_details")
        assert result.category == ErrorCategory.RECOVERABLE
        assert "get_match_details" in result.message

    def test_classify_without_context(self) -> None:
        """不传 context 参数时，消息中不包含工具名"""
        error = MCPConnectionError(MCPConnectionError.TIMEOUT, "timeout")
        result = self.classifier.classify(error)
        assert result.category == ErrorCategory.RECOVERABLE
        assert "(" not in result.message or "工具" not in result.message

    # ── ClassifiedError 基础 ──

    def test_classified_error_repr(self) -> None:
        """ClassifiedError 的 repr 包含分类和消息"""
        err = ClassifiedError(ErrorCategory.RECOVERABLE, "test message", retryable=True, detail="detail")
        assert "recoverable" in repr(err)
        assert "test message" in repr(err)
