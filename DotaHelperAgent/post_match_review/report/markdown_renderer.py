"""Markdown 报告渲染器"""
from typing import List
from post_match_review.types.report import ReviewReport
from post_match_review.types.analysis import AnalysisResult
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.report.renderer")


class MarkdownRenderer:
    """Markdown 报告渲染器"""

    def render(self, report: ReviewReport) -> str:
        """渲染 Markdown 报告

        Args:
            report: 完整复盘报告

        Returns:
            str: Markdown 格式报告
        """
        logger.info("开始渲染 Markdown 报告")

        sections: List[str] = []

        # 1. 标题
        sections.append(self._render_title(report))

        # 2. 比赛摘要
        sections.append(self._render_match_summary(report))

        # 3. 整体评估
        sections.append(self._render_overall_assessment(report))

        # 4. 各阶段分析
        sections.append(self._render_phase_analyses(report))

        # 5. 关键发现
        sections.append(self._render_key_findings(report))

        # 6. 改进建议
        sections.append(self._render_improvement_areas(report))

        # 7. 页脚
        sections.append(self._render_footer(report))

        markdown = "\n\n".join(sections)
        logger.info("Markdown 报告渲染完成，长度: %d", len(markdown))

        return markdown

    def _render_title(self, report: ReviewReport) -> str:
        """渲染标题"""
        winner = "天辉" if report.match_summary.radiant_win else "夜魇"
        return (
            f"# 赛后复盘报告\n\n"
            f"**比赛 ID**: {report.match_id}  \n"
            f"**生成时间**: {report.created_at}"
        )

    def _render_match_summary(self, report: ReviewReport) -> str:
        """渲染比赛摘要"""
        summary = report.match_summary
        duration_min = summary.duration // 60
        duration_sec = summary.duration % 60

        result_text = "胜利" if summary.user_team_win else "失败"
        winner_text = "天辉" if summary.radiant_win else "夜魇"

        lines = [
            "## 比赛摘要",
            "",
            f"- **结果**: {result_text}（{winner_text}获胜）",
            f"- **比分**: {summary.radiant_score} - {summary.dire_score}",
            f"- **时长**: {duration_min}分{duration_sec}秒",
            f"- **使用英雄**: {summary.user_hero}",
        ]

        if summary.key_events:
            lines.append("")
            lines.append("**关键事件**:")
            for event in summary.key_events:
                lines.append(f"- {event}")

        return "\n".join(lines)

    def _render_overall_assessment(self, report: ReviewReport) -> str:
        """渲染整体评估"""
        lines = [
            "## 整体评估",
            "",
            f"- **综合评分**: {report.overall_score:.1f} / 10",
            f"- **整体置信度**: {report.overall_confidence:.0%}",
            f"- **终态**: {report.terminal_state}",
        ]
        return "\n".join(lines)

    def _render_phase_analyses(self, report: ReviewReport) -> str:
        """渲染各阶段分析"""
        sections: List[str] = ["## 详细分析"]

        for result in report.phase_results:
            sections.append(self._render_single_phase(result))

        return "\n\n".join(sections)

    def _render_single_phase(self, result: AnalysisResult) -> str:
        """渲染单个阶段分析"""
        phase_names = {
            "laning": "对线期分析",
            "teamfight": "团战分析",
            "economy": "经济分析",
            "decisions": "决策分析",
            "vision": "视野分析",
            "fallback": "降级分析",
        }

        phase_display = phase_names.get(result.phase, result.phase)

        lines = [
            f"### {phase_display}",
            "",
            f"**置信度**: {result.confidence:.0%} | "
            f"**迭代次数**: {result.iterations_used} | "
            f"**结论数量**: {len(result.conclusions)}",
            "",
        ]

        for i, conclusion in enumerate(result.conclusions, 1):
            lines.append(f"**{i}. {conclusion.title}**")
            lines.append(f"{conclusion.content}")

            if conclusion.evidence:
                lines.append("")
                lines.append("*证据*:")
                for ev in conclusion.evidence:
                    lines.append(f"- `{ev}`")

            if conclusion.suggestion:
                lines.append("")
                lines.append(f"> 💡 **建议**: {conclusion.suggestion}")

            lines.append("")

        return "\n".join(lines)

    def _render_key_findings(self, report: ReviewReport) -> str:
        """渲染关键发现"""
        if not report.key_findings:
            return ""

        lines = ["## 关键发现", ""]
        for finding in report.key_findings:
            lines.append(f"- {finding}")

        return "\n".join(lines)

    def _render_improvement_areas(self, report: ReviewReport) -> str:
        """渲染改进建议"""
        if not report.improvement_areas:
            return ""

        lines = ["## 改进建议", ""]
        for area in report.improvement_areas:
            lines.append(f"- {area}")

        return "\n".join(lines)

    def _render_footer(self, report: ReviewReport) -> str:
        """渲染页脚"""
        return (
            "---\n\n"
            "*本报告由 DotaHelper 赛后复盘 Agent 自动生成*"
        )
