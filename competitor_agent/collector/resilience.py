"""单源熔断器（设计文档 74 §3.5-1）——同一源连续失败 N 次 → 熔断 T 秒并切备用源。

- closed：正常放行；连续失败达 ``threshold`` → open（指数退避：半开态再失败冷却翻倍，封顶 8×）；
- open：``allow()=False``（路由直接切下一备用源）；冷却到期 → half-open（放行一次探测）；
- half-open：探测成功 → closed（计数清零、冷却复位）；失败 → 重新 open；
- 线程安全（doc 59：单回合多 tool_calls 并发分发共享同一 router/breaker）；
- 时钟可注入（测试确定性，禁真等待）；正常路径（失败未达阈值）行为不变（黄金回归）。

接线点：``SearchRouter``（doc 71 搜索降级池逐源）与 ``FetchRouter``（三级抓取链逐级），
阈值/冷却来自 ``CollectorConfig.breaker_threshold/breaker_cooldown_seconds``；
构造入口传 0/负值 = 关闭（现状行为，直接构造的旧调用方零改动）。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

logger = logging.getLogger("competitor_agent.collector.resilience")

_CLOSED = "closed"
_OPEN = "open"
_HALF_OPEN = "half_open"

_COOLDOWN_CAP_FACTOR = 8  # 指数退避封顶：8 × 基础冷却


class CircuitBreaker:
    """线程安全单源熔断器（closed/open/half-open 三态，指数退避）。"""

    def __init__(
        self,
        name: str,
        *,
        threshold: int = 3,
        cooldown_seconds: float = 60.0,
        now_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._name = name
        self._threshold = max(1, int(threshold))
        self._base_cooldown = max(0.0, float(cooldown_seconds))
        self._cooldown = self._base_cooldown
        self._now_fn = now_fn
        self._lock = threading.Lock()
        self._state = _CLOSED
        self._failures = 0
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def allow(self) -> bool:
        """当前是否放行该源：closed/half-open 放行；open 且冷却未到期拒绝。"""
        with self._lock:
            if self._state == _OPEN:
                if self._now_fn() - self._opened_at >= self._cooldown:
                    self._state = _HALF_OPEN
                    logger.info(
                        "circuit.half_open source=%s（冷却 %.0fs 到期，放行探测）",
                        self._name, self._cooldown,
                    )
                    return True
                return False
            return True

    def record_success(self) -> None:
        """成功：回 closed、计数清零、冷却复位。"""
        with self._lock:
            if self._state != _CLOSED:
                logger.info("circuit.close source=%s（探测成功恢复）", self._name)
            self._state = _CLOSED
            self._failures = 0
            self._cooldown = self._base_cooldown

    def record_failure(self) -> None:
        """失败：closed 下连续达阈值 → open；half-open 下探测失败 → 重新 open（冷却翻倍）。"""
        with self._lock:
            self._failures += 1
            prev_state = self._state
            should_open = prev_state == _HALF_OPEN or self._failures >= self._threshold
            if not should_open:
                return
            self._opened_at = self._now_fn()
            self._state = _OPEN
            if prev_state == _HALF_OPEN and self._base_cooldown > 0:
                self._cooldown = min(
                    self._base_cooldown * _COOLDOWN_CAP_FACTOR, self._cooldown * 2
                )
            else:
                self._cooldown = self._base_cooldown
            logger.warning(
                "circuit.open source=%s failures=%d cooldown=%.0fs",
                self._name, self._failures, self._cooldown,
            )
