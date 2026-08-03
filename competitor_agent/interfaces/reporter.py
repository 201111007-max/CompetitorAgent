"""报告构建器契约"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult


@runtime_checkable
class IReportBuilder(Protocol):
    """把维度结果与未关闭缺口汇总为报告"""

    def build(
        self,
        competitor: Competitor,
        results: list[DimensionResult],
        gaps_pending: list[InfoGap],
        terminal_state: str,
    ) -> CompetitorReport:
        ...

    def to_markdown(self, report: CompetitorReport) -> str:
        ...


__all__ = ["IReportBuilder"]