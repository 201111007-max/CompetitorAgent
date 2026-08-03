"""ReporterAgent — 汇总 Agent

职责：收集校验通过的 DimensionResult，剔除/标注冲突项，
产出草稿 CompetitorReport（markdown），发布到 T_DRAFT。
"""
from __future__ import annotations

import logging

from competitor_agent.core.report_builder import ReportBuilder
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.team.message_bus import T_DRAFT, MessageBus
from competitor_agent.team.validator_agent import ValidationResult

logger = logging.getLogger("competitor_agent.team.reporter_agent")


class ReporterAgent:
    """汇总 Agent：校验后结论 → 草稿报告"""

    def __init__(
        self,
        bus: MessageBus,
        builder: ReportBuilder | None = None,
        memory: IFourLayerMemory | None = None,
    ) -> None:
        self._bus = bus
        self._builder = builder or ReportBuilder()
        self._memory = memory

    def draft(
        self,
        competitor: Competitor,
        results: list[DimensionResult],
        validation: ValidationResult,
        gaps_pending: list[InfoGap] | None = None,
    ) -> CompetitorReport:
        # 冲突项从正文剔除，仍计入待办缺口
        conflict_dims = {i.dimension for i in validation.issues if i.kind == "conflict"}
        kept = [r for r in results if r.dimension not in conflict_dims]
        report = self._builder.build(
            competitor=competitor,
            results=kept,
            gaps_pending=gaps_pending or [],
            terminal_state="success" if validation.passed else "degraded",
        )
        report.markdown_report = self._render_draft(report, validation)
        self._bus.publish(T_DRAFT, {"competitor": competitor.name, "report": report})
        return report

    def _render_draft(self, report: CompetitorReport, validation: ValidationResult) -> str:
        lines = [report.markdown_report]
        if validation.issues:
            lines.append("\n## 校验备注")
            for issue in validation.issues:
                lines.append(f"- [{issue.severity}] {issue.dimension}: {issue.message}")
        return "\n".join(lines)