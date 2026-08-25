"""BudgetController — 三条件终止决策（移除成本条件）

对照架构文档 5.3（成本条件已按设计决策移除，项目仅保留迭代门禁与
核心信息满足度，token 统计在 LLMClient）：
1) 所有缺口关闭
2) 迭代预算耗尽
3) 核心信息满足度（priority>=8 的缺口 confidence>=0.8）
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
    CORE_SATISFACTION_REACHED = "core_satisfaction_reached"
    NO_GAPS = "no_gaps"


@dataclass
class BudgetController:
    """三条件终止控制器（无成本上限；仅迭代门禁 + 核心满足度提示）"""

    max_iterations: int = 10
    core_priority_threshold: int = CORE_PRIORITY
    core_confidence: float = 0.8
    iteration_count: int = field(default=0, init=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def record_iteration(self) -> None:
        """记录一次迭代消耗（线程安全，供并行缺口共享此预算）"""
        with self._lock:
            self.iteration_count += 1

    def should_stop(self, gaps: list[InfoGap]) -> StopDecision:
        """按条件判断是否终止（成本条件已移除）。"""
        if not gaps:
            return StopDecision(should_stop=True, reason=StopReason.NO_GAPS)

        # 并行下各线程安全读共享计数（快照）
        with self._lock:
            iterations = self.iteration_count

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
        # 3) 核心信息满足度
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
            max_iterations=self.max_iterations,
        )