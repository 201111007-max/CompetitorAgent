"""停止验证器契约"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.interfaces.context import BudgetState, StopDecision


@runtime_checkable
class IStopVerifier(Protocol):
    """决定一次分析是否可终止（由 Hook 验证，而非预算单方面决定）"""

    def verify(self, gaps: list[InfoGap], budget_state: BudgetState) -> StopDecision:
        """返回：可停（含 reason）/ 不可停（含缺口原因）"""
        ...


__all__ = ["IStopVerifier"]
