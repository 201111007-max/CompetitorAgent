"""维度分析器契约"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from competitor_agent.domain_types.enums import DimensionType
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.interfaces.context import AnalysisContext


@runtime_checkable
class ICompetitorAnalyzer(Protocol):
    """单个维度（功能/定价/性能/生态/口碑）的分析器"""

    @property
    def dimension(self) -> DimensionType:
        """本分析器负责的维度"""
        ...

    def analyze(
        self,
        observation: Observation,
        gap: InfoGap,
        context: AnalysisContext,
    ) -> DimensionResult:
        """把原始 Observation 提炼为维度结论（含置信度与证据）。

        异常约定：
        - AnalysisNotApplicableError: Observation 与维度不匹配，返回空结论
        """
        ...

    def confidence(self, result: DimensionResult) -> float:
        """结论置信度 0-1，供 BudgetController 评估核心满足度"""
        ...


__all__ = ["ICompetitorAnalyzer"]
