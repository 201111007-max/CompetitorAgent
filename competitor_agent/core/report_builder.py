"""ReportBuilder — 汇总维度结果与未关闭缺口为报告"""
from __future__ import annotations

from competitor_agent.core.markdown_renderer import MarkdownRenderer
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult
from competitor_agent.observability.logger import get_logger

logger = get_logger("core.report_builder")

# 维度权重（用于综合评分）
_DIMENSION_WEIGHTS = {
    "pricing": 0.25,
    "feature": 0.25,
    "performance": 0.2,
    "ecosystem": 0.1,
    "sentiment": 0.1,
    "roadmap": 0.1,
}


class ReportBuilder:
    """实现 IReportBuilder：汇总 + 渲染"""

    def __init__(self, renderer: MarkdownRenderer | None = None) -> None:
        self._renderer = renderer or MarkdownRenderer()

    def build(
        self,
        competitor: Competitor,
        results: list[DimensionResult],
        gaps_pending: list[InfoGap],
        terminal_state: str,
    ) -> CompetitorReport:
        overall_score, overall_confidence = self._aggregate(results)
        report = CompetitorReport(
            competitor=competitor,
            dimension_results=results,
            overall_score=overall_score,
            overall_confidence=overall_confidence,
            gaps_pending=gaps_pending,
            terminal_state=terminal_state,
        )
        report.markdown_report = self.to_markdown(report)
        return report

    def _aggregate(self, results: list[DimensionResult]) -> tuple[float, float]:
        if not results:
            return 0.0, 0.0
        total_weight = 0.0
        score = 0.0
        confidence = 0.0
        for r in results:
            w = _DIMENSION_WEIGHTS.get(r.dimension, 0.1)
            total_weight += w
            score += w * r.confidence
            confidence += w * r.confidence
        return score / total_weight, confidence / total_weight

    def to_markdown(self, report: CompetitorReport) -> str:
        return self._renderer.render(report)