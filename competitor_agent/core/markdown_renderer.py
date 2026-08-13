"""Markdown 渲染器 — 把 CompetitorReport 渲染为 Markdown"""
from __future__ import annotations

from collections.abc import Sequence

from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.domain_types.report import ComparisonReport, CompetitorReport, DimensionResult
from competitor_agent.observability.logger import get_logger

logger = get_logger("core.markdown_renderer")

_STATUS_LABEL = {
    ResultStatus.COMPLETE: "[OK]",
    ResultStatus.PARTIAL: "[PARTIAL]",
    ResultStatus.UNAVAILABLE: "[N/A]",
}

# 每维度最佳排序：状态权重 + 置信度
_STATUS_RANK = {
    ResultStatus.COMPLETE: 3,
    ResultStatus.PARTIAL: 2,
    ResultStatus.UNAVAILABLE: 1,
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
        if report.freshness is not None:
            note = report.freshness.markdown_note()
            if note:
                lines.append(note)
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

    def render_timeline(self, events: Sequence[object]) -> str:
        """渲染竞品时间线 Markdown 段落（设计文档 26 §3.4）。

        ``events`` 为 ``TimelineEvent``（duck-type 出 event_type/summary/occurred_at/evidence_urls）。
        """
        if not events:
            return ""
        lines = ["## 竞品时间线", ""]
        lines.append("| 日期 | 类型 | 变化 | 证据 |")
        lines.append("|------|------|------|------|")
        for ev in events:
            occurred = str(getattr(ev, "occurred_at", ""))[:10] or "-"
            event_type = str(getattr(ev, "event_type", "change"))
            summary = _truncate(str(getattr(ev, "summary", "") or ""), 80)
            urls = getattr(ev, "evidence_urls", None) or []
            if isinstance(urls, dict):
                urls = list(urls.values())
            evidence = ", ".join(str(u) for u in urls[:2]) or "-"
            lines.append(f"| {occurred} | {event_type} | {summary} | {evidence} |")
        return "\n".join(lines)

    def render_comparison(self, report: ComparisonReport) -> str:
        """渲染多竞品品类格局对比报告（设计文档 20）：
        - 品类格局矩阵：| 维度 | 竞品A | 竞品B | ... | 最佳 |
        - 每维度最佳：按置信度 + 状态（[OK] > [PARTIAL] > [N/A]）给出最佳竞品与一句话摘要
        - 汇总视图：整体置信度排名 + 维度覆盖缺口汇总
        """
        reports = report.reports
        if not reports:
            return "# 竞品格局对比报告\n\n_无可用竞品报告。_\n"

        names = [r.competitor.name for r in reports]
        dims_by_rep = [{r.dimension: r for r in r.dimension_results} for r in reports]
        all_dims = list(dict.fromkeys(d for dmap in dims_by_rep for d in dmap))

        lines: list[str] = []
        lines.append(f"# {' vs '.join(names)} 竞品格局对比报告")
        lines.append("")
        lines.append(f"> 对比竞品: {', '.join(names)}")
        lines.append(f"> 生成时间: {report.created_at}")
        lines.append("")

        # ── 品类格局矩阵 ──────────────────────────────────────────────
        lines.append("## 品类格局矩阵")
        lines.append("")
        header = ["维度", *names, "最佳"]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "|".join(["------"] + [":---:" for _ in names] + [":---:"]) + "|")
        best_per_dim: dict[str, tuple[str, float, ResultStatus | None, str]] = {}
        for dim in all_dims:
            row = [dim]
            for dmap in dims_by_rep:
                r = dmap.get(dim)
                row.append(_fmt_confidence(r))
            best = _best_for_dim(dim, reports, dims_by_rep)
            best_per_dim[dim] = best
            row.append(best[0] if best[0] else "-")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

        # ── 每维度最佳 ────────────────────────────────────────────────
        lines.append("## 每维度最佳")
        lines.append("")
        if best_per_dim:
            for dim, (best_name, conf, status, summary) in best_per_dim.items():
                if not best_name:
                    lines.append(f"- **{dim}**: 无可用结论")
                    continue
                label = _STATUS_LABEL.get(status, "") if status else ""
                lines.append(f"- **{dim}**: {label} **{best_name}**（置信度 {conf:.2f}）— {summary or '（无摘要）'}")
        else:
            lines.append("_无任何维度结论。_")
        lines.append("")

        # ── 汇总视图 ──────────────────────────────────────────────────
        lines.append("## 汇总")
        lines.append("")
        ranked = sorted(
            ((r.competitor.name, r.overall_confidence) for r in reports),
            key=lambda x: x[1],
            reverse=True,
        )
        lines.append("### 整体置信度排名")
        lines.append("")
        for idx, (name, conf) in enumerate(ranked, 1):
            lines.append(f"{idx}. **{name}** — {conf:.2f}")
        lines.append("")
        lines.append("### 维度覆盖缺口")
        lines.append("")
        coverage = []
        for name, dmap in zip(names, dims_by_rep):
            missing = [d for d in all_dims if d not in dmap]
            if missing:
                coverage.append(f"- {name} 缺: {', '.join(missing)}")
        if coverage:
            lines.extend(coverage)
        else:
            lines.append("_全部竞品覆盖所有已产出维度。_")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("_本报告由 competitor_agent 自动生成。_")
        return "\n".join(lines)


def _fmt_confidence(result: DimensionResult | None) -> str:
    if result is None:
        return "N/A"
    label = _STATUS_LABEL.get(result.status, "")
    return f"{label} {result.confidence:.2f}" if label else f"{result.confidence:.2f}"


def _best_for_dim(
    dim: str,
    reports: list[CompetitorReport],
    dims_by_rep: list[dict[str, DimensionResult]],
) -> tuple[str, float, ResultStatus | None, str]:
    """维度最佳：按状态（[OK] > [PARTIAL] > [N/A]）+ 置信度排序取最优。"""
    best: tuple[str, float, ResultStatus | None, str] | None = None
    for report, dmap in zip(reports, dims_by_rep):
        r = dmap.get(dim)
        if r is None:
            continue
        rank = _STATUS_RANK.get(r.status, 0)
        if best is None:
            best = (report.competitor.name, r.confidence, r.status, r.summary)
            continue
        if rank > _STATUS_RANK.get(best[2], 0) or (
            rank == _STATUS_RANK.get(best[2], 0) and r.confidence > best[1]
        ):
            best = (report.competitor.name, r.confidence, r.status, r.summary)
    return best if best is not None else ("", 0.0, None, "")


def _truncate(text: str, limit: int = 80) -> str:
    """截断长文本为一行（超限加省略号）"""
    if not text:
        return ""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "…"