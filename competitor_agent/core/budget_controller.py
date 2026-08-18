"""BudgetController — 四条件终止决策

对照架构文档 5.3：
1) 所有缺口关闭
2) 迭代预算耗尽
3) 成本上限（美元）
4) 核心信息满足度（priority>=8 的缺口 confidence>=0.8）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from competitor_agent.domain_types.enums import GapStatus
from competitor_agent.domain_types.info_gap import CORE_PRIORITY, InfoGap
from competitor_agent.interfaces.context import BudgetState, StopDecision


@dataclass
class StopReason:
    """终止原因枚举常量"""

    ALL_GAPS_CLOSED = "all_gaps_closed"
    ITERATION_BUDGET_EXHAUSTED = "iteration_budget_exhausted"
    COST_LIMIT_REACHED = "cost_limit_reached"
    CORE_SATISFACTION_REACHED = "core_satisfaction_reached"
    NO_GAPS = "no_gaps"


@dataclass
class BudgetController:
    """四条件终止控制器"""

    max_iterations: int = 10
    cost_limit: float = 1.0
    core_priority_threshold: int = CORE_PRIORITY
    core_confidence: float = 0.8
    iteration_count: int = field(default=0, init=False)
    total_cost: float = field(default=0.0, init=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def record_iteration(self, cost: float = 0.0) -> None:
        """记录一次迭代消耗（线程安全，供并行缺口共享此预算）"""
        with self._lock:
            self.iteration_count += 1
            self.total_cost += cost

    def should_stop(self, gaps: list[InfoGap]) -> StopDecision:
        """按四条件判断是否终止。"""
        if not gaps:
            return StopDecision(should_stop=True, reason=StopReason.NO_GAPS)

        # 并行下各线程安全读共享计数（快照）
        with self._lock:
            iterations = self.iteration_count
            total_cost = self.total_cost

        # 1) 所有缺口关闭
        if all(g.status in (GapStatus.CLOSED, GapStatus.CONFIRMED) for g in gaps):
            return StopDecision(should_stop=True, reason=StopReason.ALL_GAPS_CLOSED)
        # 2) 迭代预算耗尽
        if iterations >= self.max_iterations:
            return StopDecision(
                should_stop=True,
                reason=StopReason.ITERATION_BUDGET_EXHAUSTED,
                details=f"iterations={iterations}/{self.max_iterations}",
            )
        # 3) 成本上限
        if total_cost >= self.cost_limit:
            return StopDecision(
                should_stop=True,
                reason=StopReason.COST_LIMIT_REACHED,
                details=f"cost=${total_cost:.4f}",
            )
        # 4) 核心信息满足度
        if self._core_satisfied(gaps):
            core_gaps = [g for g in gaps if g.priority >= self.core_priority_threshold]
            return StopDecision(
                should_stop=True,
                reason=StopReason.CORE_SATISFACTION_REACHED,
                details=f"core={len(core_gaps)} gaps satisfied",
            )
        return StopDecision(should_stop=False)

    def _core_satisfied(self, gaps: list[InfoGap]) -> bool:
        core_gaps = [g for g in gaps if g.priority >= self.core_priority_threshold]
        return bool(core_gaps) and all(g.confidence >= self.core_confidence for g in core_gaps)

    def to_budget_state(self) -> BudgetState:
        """导出预算状态快照"""
        return BudgetState(
            iterations_used=self.iteration_count,
            total_cost=self.total_cost,
            max_iterations=self.max_iterations,
            cost_limit=self.cost_limit,
        )
