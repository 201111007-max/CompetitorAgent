"""迭代预算控制器：迭代 + token 边际递减

从 dota_helper/engines/budget.py 通用化迁移，并移除成本核算：
- 记录迭代次数（预算门禁）
- 按 token 做边际递减启发（供停止决策参考），保留 token 统计但不再折算美元成本
- 提供 consume() / refund() / 剩余资源查询
- ThreadSafe（供并行子代理共享）
"""

from __future__ import annotations

import logging
from threading import Lock

logger = logging.getLogger("competitor_agent.core.budget")


class IterationBudget:
    """迭代预算控制器（仅迭代门禁 + token 边际递减，无美元成本）

    成本已从核心运行路径移除（设计决策）：预算按迭代次数收敛，
    token 统计仅在求边际递减时使用，不再作为美元成本记账。
    """

    def __init__(
        self,
        max_iterations: int,
        diminishing_threshold: int = 500,
        min_continuations: int = 3,
    ) -> None:
        self._max_iterations = max_iterations
        self._diminishing_threshold = diminishing_threshold
        self._min_continuations = min_continuations

        self._used_iterations = 0
        self._recent_deltas: list[int] = []
        self._lock = Lock()

    def consume(self, delta_tokens: int = 0) -> bool:
        """消费一个迭代配额，返回 True 表示允许继续，False 表示预算耗尽/递减。

        预算仅按迭代数收敛（无成本上限）；是否真正停止由调用方综合判断。
        """
        with self._lock:
            if self._used_iterations >= self._max_iterations:
                logger.warning("预算控制器: 迭代耗尽 %d/%d", self._used_iterations, self._max_iterations)
                return False
            if self._used_iterations >= self._min_continuations and self._check_diminishing(delta_tokens):
                logger.info("预算控制器: 边际递减，建议停止")
                return False

            self._used_iterations += 1
            self._recent_deltas.append(delta_tokens)
            if len(self._recent_deltas) > 2:
                self._recent_deltas.pop(0)
            return True

    def _check_diminishing(self, current_delta: int) -> bool:
        if len(self._recent_deltas) < 2:
            return False
        recent = self._recent_deltas[-2:]
        return (
            all(d < self._diminishing_threshold for d in recent)
            and current_delta < self._diminishing_threshold
        )

    def refund(self) -> None:
        """退还一个迭代配额（采集失败无需耗时）"""
        with self._lock:
            if self._used_iterations > 0:
                self._used_iterations -= 1

    def snapshot(self) -> tuple[int, int]:
        """返回 (已用迭代, 总迭代)"""
        with self._lock:
            return (self._used_iterations, self._max_iterations)

    @property
    def used_iterations(self) -> int:
        with self._lock:
            return self._used_iterations

    @property
    def remaining_iterations(self) -> int:
        return self._max_iterations - self._used_iterations