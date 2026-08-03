"""Markdown 渲染器 — 把 CompetitorReport 渲染为 Markdown"""
from __future__ import annotations

from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult
from competitor_agent.observability.logger import get_logger

logger = get_logger("core.markdown_renderer")

_STATUS_LABEL = {
    ResultStatus.COMPLETE: "[OK]",
    ResultStatus.PARTIAL: "[PARTIAL]",
    ResultStatus.UNAVAILABLE: "[N/A]",
}


class MarkdownRenderer:
    """渲染单竞品报告为 Markdown"""

    def render(self, report: CompetitorReport) -> str:
        lines: list[str] = []
        lines.append(f"# {report.competitor.name} 竞品分析报告")
        lines.append("")
        lines.append(f"> 生成时间: {report.created_at}")
        lines.append(f"> 终态: `{report.terminal_state}`")
        lines.append(f"> 综合置信度: **{report.overall_confidence:.2f}**")
        lines.append("")
        lines.append("## 维度结论")
        lines.append("")

        for result in report.dimension_results:
            self._render_dimension(lines, result)

        lines.append("## 未关闭缺口")
        lines.append("")
        if report.gaps_pending:
            for gap in report.gaps_pending:
                tried = ", ".join(gap.sources_tried) or "无"
                lines.append(f"- **{gap.field}** (priority={gap.priority}, confidence={gap.confidence:.2f})")
                lines.append(f"  - 已尝试源: {tried}")
                lines.append(f"  - 状态: {gap.status.value}")
        else:
            lines.append("_全部缺口已关闭或无待处理缺口。_")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("_本报告由 competitor_agent 自动生成。_")
        return "\n".join(lines)

    def _render_dimension(self, lines: list[str], result: DimensionResult) -> None:
        label = _STATUS_LABEL.get(result.status, "•")
        lines.append(f"### {label} {result.dimension}")
        lines.append("")
        lines.append(result.summary or "（无结论）")
        lines.append("")
        if result.details:
            lines.append("明细:")
            lines.append("")
            lines.append("```")
            lines.append(str(result.details)[:1000])
            lines.append("```")
            lines.append("")
        lines.append(f"置信度: `{result.confidence:.2f}`")
        if result.evidence:
            urls = ", ".join(ev.url for ev in result.evidence if ev.url)
            if urls:
                lines.append(f"证据: {urls}")
        lines.append("")