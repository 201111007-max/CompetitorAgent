"""熔断器单元测试"""
import time

import pytest

from dota_helper.agent.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitState,
)


class TestCircuitBreaker:
    """测试单个工具的熔断器状态机"""

    def test_initial_state_is_closed(self) -> None:
        """初始状态为 CLOSED"""
        cb = CircuitBreaker(name="test_tool")
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_allow_request_returns_true_when_closed(self) -> None:
        """CLOSED 状态允许调用"""
        cb = CircuitBreaker(name="test_tool")
        assert cb.allow_request() is True

    def test_opens_after_failure_threshold(self) -> None:
        """连续失败达到阈值 → OPEN"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60, name="test_tool")
        cb.on_failure()  # 1
        assert cb.state == CircuitState.CLOSED
        cb.on_failure()  # 2
        assert cb.state == CircuitState.CLOSED
        cb.on_failure()  # 3 → OPEN
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_stays_closed_below_threshold(self) -> None:
        """失败次数低于阈值时保持 CLOSED"""
        cb = CircuitBreaker(failure_threshold=5, name="test_tool")
        for _ in range(4):
            cb.on_failure()
        assert cb.state == CircuitState.CLOSED

    def test_success_resets_failure_count(self) -> None:
        """成功调用重置失败计数"""
        cb = CircuitBreaker(failure_threshold=3, name="test_tool")
        cb.on_failure()
        cb.on_failure()
        cb.on_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_half_open_after_timeout(self) -> None:
        """OPEN 超时后自动切换到 HALF_OPEN"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01, name="test_tool")
        cb.on_failure()  # → OPEN
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        # 访问 state 属性触发自动恢复检查
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True

    def test_half_open_success_returns_to_closed(self) -> None:
        """HALF_OPEN 成功 → CLOSED"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01, name="test_tool")
        cb.on_failure()  # → OPEN
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN
        cb.on_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_half_open_failure_doubles_timeout(self) -> None:
        """HALF_OPEN 失败 → OPEN，超时加倍"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, name="test_tool")
        cb.on_failure()  # → OPEN, timeout=10
        time.sleep(0.01)
        # 手动触发 HALF_OPEN
        cb._state = CircuitState.HALF_OPEN
        cb.on_failure()  # → OPEN, timeout=20
        assert cb.state == CircuitState.OPEN
        assert cb._current_timeout == 20.0

    def test_timeout_capped_at_300_seconds(self) -> None:
        """超时最大值 300 秒"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, name="test_tool")
        # 连续触发 HALF_OPEN 失败，超时应被 cap 在 300
        for _ in range(10):
            cb._state = CircuitState.HALF_OPEN
            cb.on_failure()
        assert cb._current_timeout == 300.0

    def test_reset_restores_closed(self) -> None:
        """手动重置恢复到 CLOSED"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60, name="test_tool")
        cb.on_failure()  # → OPEN
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.allow_request() is True

    def test_allow_request_returns_false_when_open(self) -> None:
        """OPEN 状态拒绝调用"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60, name="test_tool")
        cb.on_failure()
        assert cb.allow_request() is False


class TestCircuitBreakerRegistry:
    """测试熔断器注册表"""

    def test_get_creates_new_breaker(self) -> None:
        """获取不存在的工具时自动创建熔断器"""
        registry = CircuitBreakerRegistry()
        cb = registry.get("get_match_details")
        assert cb is not None
        assert cb.state == CircuitState.CLOSED

    def test_get_returns_same_instance(self) -> None:
        """同一工具名返回同一熔断器实例"""
        registry = CircuitBreakerRegistry()
        cb1 = registry.get("test_tool")
        cb2 = registry.get("test_tool")
        assert cb1 is cb2

    def test_allow_request_delegates(self) -> None:
        """allow_request 委托给对应熔断器"""
        registry = CircuitBreakerRegistry()
        assert registry.allow_request("tool_a") is True
        assert registry.allow_request("tool_b") is True

    def test_on_success_and_on_failure(self) -> None:
        """on_success / on_failure 委托给对应熔断器"""
        registry = CircuitBreakerRegistry(default_failure_threshold=1)
        registry.on_failure("tool_a")
        assert registry.allow_request("tool_a") is False  # 熔断
        assert registry.allow_request("tool_b") is True   # 不受影响

        registry.on_success("tool_a")
        assert registry.allow_request("tool_a") is True   # 恢复

    def test_open_tools_returns_failed_tools(self) -> None:
        """open_tools 返回当前熔断的工具列表"""
        registry = CircuitBreakerRegistry(default_failure_threshold=1, default_recovery_timeout=60)
        registry.on_failure("tool_a")
        registry.on_failure("tool_b")
        open_tools = registry.open_tools
        assert "tool_a" in open_tools
        assert "tool_b" in open_tools
        assert open_tools["tool_a"] > 0

    def test_open_tools_excludes_closed_tools(self) -> None:
        """open_tools 不包含 CLOSED 状态的工具"""
        registry = CircuitBreakerRegistry(default_failure_threshold=1)
        registry.on_failure("tool_a")
        open_tools = registry.open_tools
        assert "tool_a" in open_tools
        assert "tool_b" not in open_tools

    def test_reset_single_tool(self) -> None:
        """reset 单个工具"""
        registry = CircuitBreakerRegistry(default_failure_threshold=1)
        registry.on_failure("tool_a")
        registry.on_failure("tool_b")
        registry.reset("tool_a")
        assert registry.allow_request("tool_a") is True
        assert registry.allow_request("tool_b") is False

    def test_reset_all_tools(self) -> None:
        """reset 所有工具"""
        registry = CircuitBreakerRegistry(default_failure_threshold=1)
        registry.on_failure("tool_a")
        registry.on_failure("tool_b")
        registry.reset()
        assert registry.allow_request("tool_a") is True
        assert registry.allow_request("tool_b") is True

    def test_tools_are_independent(self) -> None:
        """不同工具的熔断器互不影响"""
        registry = CircuitBreakerRegistry(default_failure_threshold=3)
        registry.on_failure("tool_a")
        registry.on_failure("tool_a")
        # tool_a 失败 2 次，未熔断
        assert registry.allow_request("tool_a") is True
        # tool_b 从未失败
        assert registry.allow_request("tool_b") is True
        registry.on_failure("tool_a")  # 第 3 次 → 熔断
        assert registry.allow_request("tool_a") is False
        assert registry.allow_request("tool_b") is True
