"""工具级熔断器 — 防止连续失败的工具被反复调用

状态机：
  CLOSED（关闭）→ 连续失败达到阈值 → OPEN（断开）
  OPEN（断开）→ 超时后 → HALF_OPEN（半开）
  HALF_OPEN（半开）→ 成功 → CLOSED（关闭）
  HALF_OPEN（半开）→ 失败 → OPEN（断开，超时加倍）

每个工具独立维护一个熔断器实例。
"""
import time
from enum import Enum
from typing import Dict, Optional

from dota_helper.observability.logger import get_logger

logger = get_logger("agent.circuit_breaker")


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"         # 正常，允许调用
    OPEN = "open"             # 熔断，拒绝调用
    HALF_OPEN = "half_open"   # 半开，允许试探性调用


class CircuitBreaker:
    """单个工具的熔断器

    Args:
        failure_threshold: 连续失败次数阈值（默认 3）
        recovery_timeout: 熔断恢复时间（秒，默认 30）
        name: 工具名称（日志用）
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        name: str = "",
    ) -> None:
        self._failure_threshold = failure_threshold
        self._base_recovery_timeout = recovery_timeout
        self._name = name

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._current_timeout = recovery_timeout

    @property
    def state(self) -> CircuitState:
        """当前熔断器状态"""
        # 检查 OPEN 状态是否超时，自动切换到 HALF_OPEN
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self._current_timeout:
                logger.info(
                    "熔断器超时恢复: tool=%s, elapsed=%.1fs, timeout=%.1fs",
                    self._name, elapsed, self._current_timeout,
                )
                self._state = CircuitState.HALF_OPEN
        return self._state

    def allow_request(self) -> bool:
        """检查是否允许调用此工具

        Returns:
            bool: True 允许调用，False 熔断中
        """
        state = self.state  # 触发自动恢复检查
        if state == CircuitState.OPEN:
            logger.warning(
                "熔断器阻止调用: tool=%s, failure_count=%d, remaining=%.1fs",
                self._name, self._failure_count,
                self._current_timeout - (time.time() - self._last_failure_time),
            )
            return False
        return True

    def on_success(self) -> None:
        """调用成功时调用"""
        if self._state == CircuitState.HALF_OPEN:
            logger.info("熔断器恢复: tool=%s, HALF_OPEN → CLOSED", self._name)

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._current_timeout = self._base_recovery_timeout

    def on_failure(self) -> None:
        """调用失败时调用"""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            # 半开状态下失败 → 重新熔断，超时加倍
            self._current_timeout = min(self._current_timeout * 2, 300.0)  # 最大 5 分钟
            self._state = CircuitState.OPEN
            logger.warning(
                "熔断器半开失败: tool=%s, timeout=%.1fs",
                self._name, self._current_timeout,
            )
        elif self._failure_count >= self._failure_threshold:
            # 连续失败达到阈值 → 熔断
            self._state = CircuitState.OPEN
            logger.warning(
                "熔断器触发: tool=%s, failures=%d/%d, timeout=%.1fs",
                self._name, self._failure_count,
                self._failure_threshold, self._current_timeout,
            )

    @property
    def failure_count(self) -> int:
        """当前连续失败次数"""
        return self._failure_count

    def reset(self) -> None:
        """手动重置熔断器"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._current_timeout = self._base_recovery_timeout
        logger.info("熔断器手动重置: tool=%s", self._name)


class CircuitBreakerRegistry:
    """熔断器注册表 — 管理所有工具的熔断器

    每个工具名对应一个独立的 CircuitBreaker 实例。
    """

    def __init__(
        self,
        default_failure_threshold: int = 3,
        default_recovery_timeout: float = 30.0,
    ) -> None:
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._default_failure_threshold = default_failure_threshold
        self._default_recovery_timeout = default_recovery_timeout

    def get(self, tool_name: str) -> CircuitBreaker:
        """获取指定工具的熔断器（不存在则自动创建）

        Args:
            tool_name: 工具名称

        Returns:
            CircuitBreaker: 熔断器实例
        """
        if tool_name not in self._breakers:
            self._breakers[tool_name] = CircuitBreaker(
                failure_threshold=self._default_failure_threshold,
                recovery_timeout=self._default_recovery_timeout,
                name=tool_name,
            )
        return self._breakers[tool_name]

    def allow_request(self, tool_name: str) -> bool:
        """检查是否允许调用指定工具

        Args:
            tool_name: 工具名称

        Returns:
            bool: True 允许调用
        """
        return self.get(tool_name).allow_request()

    def on_success(self, tool_name: str) -> None:
        """记录工具调用成功

        Args:
            tool_name: 工具名称
        """
        self.get(tool_name).on_success()

    def on_failure(self, tool_name: str) -> None:
        """记录工具调用失败

        Args:
            tool_name: 工具名称
        """
        self.get(tool_name).on_failure()

    def reset(self, tool_name: Optional[str] = None) -> None:
        """重置熔断器

        Args:
            tool_name: 工具名称（None 表示重置所有）
        """
        if tool_name:
            breaker = self._breakers.get(tool_name)
            if breaker:
                breaker.reset()
        else:
            for breaker in self._breakers.values():
                breaker.reset()

    @property
    def open_tools(self) -> Dict[str, float]:
        """当前处于熔断状态的工具列表

        Returns:
            Dict[str, float]: {工具名: 剩余恢复时间(秒)}
        """
        now = time.time()
        result = {}
        for name, breaker in self._breakers.items():
            if breaker.state == CircuitState.OPEN:
                remaining = breaker._current_timeout - (now - breaker._last_failure_time)
                if remaining > 0:
                    result[name] = round(remaining, 1)
        return result
