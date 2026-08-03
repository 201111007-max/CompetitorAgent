"""迭代预算控制器：迭代 + 成本 + 边际递减

从 dota_helper/engines/budget.py 通用化迁移：
- 记录迭代次数与已消耗成本（美元）
- 提供 consume() / refund() / 剩余资源查询
- ThreadSafe（供并行子代理共享）
"""
from __future__ import annotations

import logging
from threading import Lock

logger = logging.getLogger("competitor_agent.core.budget")


class IterationBudget:
    """迭代 + 成本预算控制器"""

    def __init__(
        self,
        max_iterations: int,
        cost_limit: float,
        diminishing_threshold: int = 500,
        min_continuations: int = 3,
    ) -> None:
        self._max_iterations = max_iterations
        self._cost_limit = cost_limit
        self._diminishing_threshold = diminishing_threshold
        self._min_continuations = min_continuations

        self._used_iterations = 0
        self._used_cost = 0.0
        self._recent_deltas: list[int] = []
        self._lock = Lock()

    def consume(self, delta_cost: float = 0.0, delta_tokens: int = 0) -> bool:
        """消费一个迭代配额。返回 True 表示允许继续，False 表示预算耗尽/递减。

        与 dota_helper 不同：这里消费迭代 + 累计成本，
        是否真正停止由 BudgetController 综合四条件判定。
        """
        with self._lock:
            if self._used_iterations >= self._max_iterations:
                logger.warning("预算控制器: 迭代耗尽 %d/%d", self._used_iterations, self._max_iterations)
                return False
            if self._used_cost >= self._cost_limit:
                logger.warning("预算控制器: 成本耗尽 %.4f/%.4f", self._used_cost, self._cost_limit)
                return False
            if self._used_iterations >= self._min_continuations and self._check_diminishing(delta_tokens):
                logger.info("预算控制器: 边际递减，建议停止")
                return False

            self._used_iterations += 1
            self._used_cost += delta_cost
            self._recent_deltas.append(delta_tokens)
            if len(self._recent_deltas) > 2:
                self._recent_deltas.pop(0)
            return True

    def _check_diminishing(self, current_delta: int) -> bool:
        if len(self._recent_deltas) < 2:
            return False
        recent = self._recent_deltas[-2:]
        return all(d < self._diminishing_threshold for d in recent) and current_delta < self._diminishing_threshold

    def refund(self) -> None:
        """退还一个迭代配额（采集失败无需耗时）"""
        with self._lock:
            if self._used_iterations > 0:
                self._used_iterations -= 1

    def snapshot(self) -> tuple[int, int, float, float]:
        """返回 (已用迭代, 总迭代, 已用成本, 成本上限)"""
        with self._lock:
            return (self._used_iterations, self._max_iterations, self._used_cost, self._cost_limit)

    @property
    def used_iterations(self) -> int:
        return self._used_iterations

    @property
    def used_cost(self) -> float:
        return self._used_cost

    @property
    def remaining_iterations(self) -> int:
        return self._max_iterations - self._used_iterations