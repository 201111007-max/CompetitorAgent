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
from competitor_agent.team.base_agent import AgentContext, AgentResult, AgentStatus, BaseAgent
from competitor_agent.team.message_bus import T_DRAFT, MessageBus
from competitor_agent.team.validator_agent import ValidationResult

logger = logging.getLogger("competitor_agent.team.reporter_agent")


class ReporterAgent(BaseAgent):
    """汇总 Agent：校验后结论 → 草稿报告"""

    def __init__(
        self,
        bus: MessageBus,
        builder: ReportBuilder | None = None,
        memory: IFourLayerMemory | None = None,
    ) -> None:
        super().__init__("reporter", bus, memory)
        self._builder = builder or ReportBuilder()

    def run(self, ctx: AgentContext) -> AgentResult:
        """决策入口：汇总校验后结论，产出草稿报告。"""
        results = ctx.extra.get("results", [])
        validation = ctx.extra.get("validation")
        if validation is None:
            return AgentResult(
                status=AgentStatus.DEGRADED,
                payload=None,
                reason="缺少校验结果，无法汇总报告",
            )
        try:
            report = self.draft(
                competitor=ctx.strategy.competitor,
                results=results,
                validation=validation,
                gaps_pending=[g for g in ctx.strategy.gaps if not g.is_closed],
                cross_dimension_conflicts=ctx.extra.get("cross_dimension_conflicts"),
                review=ctx.extra.get("review"),
            )
        except Exception as exc:  # noqa: BLE001 — 汇总失败统一走重试/降级
            return self._retry(ctx, exc)
        return AgentResult(status=AgentStatus.SUCCESS, payload=report)

    def draft(
        self,
        competitor: Competitor,
        results: list[DimensionResult],
        validation: ValidationResult,
        gaps_pending: list[InfoGap] | None = None,
        cross_dimension_conflicts: list | None = None,
        review: object | None = None,  # ReviewResult（设计文档 49 §3.3）
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
        report.markdown_report = self._render_draft(
            report, validation, cross_dimension_conflicts, review
        )
        self._bus.publish(T_DRAFT, {"competitor": competitor.name, "report": report})
        return report

    def _render_draft(
        self,
        report: CompetitorReport,
        validation: ValidationResult,
        cross_dimension_conflicts: list | None = None,
        review: object | None = None,
    ) -> str:
        lines = [report.markdown_report]
        if validation.issues:
            lines.append("\n## 校验备注")
            for issue in validation.issues:
                lines.append(f"- [{issue.severity}] {issue.dimension}: {issue.message}")
        conflicts = [r for r in report.dimension_results if r.conflict_evidence]
        if conflicts:
            lines.append("\n## 多来源仲裁备注")
            for result in conflicts:
                for note in result.conflict_evidence:
                    lines.append(f"- {result.dimension}: 采纳现结论，丢弃 {note}")
        if cross_dimension_conflicts:
            lines.append("\n## 跨维度冲突备注")
            for conflict in cross_dimension_conflicts:
                lines.append(f"- {conflict.summary}")
        if review is not None and getattr(review, "issues", None):
            lines.append("\n## 对抗式评审备注")
            for issue in review.issues:
                lines.append(f"- [REVIEWED] {issue.dimension}: {issue.message}")
        return "\n".join(lines)