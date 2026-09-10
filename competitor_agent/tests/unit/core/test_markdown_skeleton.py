"""设计文档 88 §4.3 —— render_skeleton / inject_slots 单测。

覆盖：骨架三处槽位占位及位置（exec 在 H1 元信息后 / dimension_insight 在置信度行前 /
market_conclusion 在「## 市场格局结论」下）、无 details blob、pricing 表保留、
show_gaps 段与 render() 同构、inject 降级注记/多余键忽略/独占行匹配。
"""

from __future__ import annotations

from competitor_agent.core.markdown_renderer import (
    MarkdownRenderer,
    inject_slots,
)
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult


def _report() -> CompetitorReport:
    return CompetitorReport(
        competitor=Competitor(name="cursor"),
        dimension_results=[
            DimensionResult(
                dimension="pricing",
                summary="Pro 档 $20/月",
                details={"plans": [{"name": "Pro", "monthly_price_usd": 20}]},
                confidence=0.8,
                status=ResultStatus.COMPLETE,
            ),
            DimensionResult(
                dimension="feature",
                summary="支持 MCP",
                details={"features": ["支持 MCP 协议"]},
                confidence=0.6,
                status=ResultStatus.COMPLETE,
            ),
        ],
        overall_confidence=0.7,
        terminal_state="success",
        created_at="2026-09-10T00:00:00+00:00",
    )


class TestRenderSkeleton:
    def test_three_slot_placeholders(self) -> None:
        skeleton = MarkdownRenderer().render_skeleton(_report())
        assert "{{slot:executive_summary}}" in skeleton
        assert "{{slot:dimension_insight:pricing}}" in skeleton
        assert "{{slot:dimension_insight:feature}}" in skeleton
        assert "{{slot:market_conclusion}}" in skeleton

    def test_slot_positions(self) -> None:
        skeleton = MarkdownRenderer().render_skeleton(_report())
        assert "## 执行摘要" in skeleton  # 槽位标题由骨架渲染（代码），writer 只产 prose
        assert skeleton.index("## 执行摘要") < skeleton.index("{{slot:executive_summary}}")
        assert skeleton.index("{{slot:executive_summary}}") < skeleton.index("## 维度结论")
        pricing_section = skeleton.index("### [OK] pricing")
        assert skeleton.index("{{slot:dimension_insight:pricing}}") > pricing_section
        assert skeleton.index("{{slot:market_conclusion}}") > skeleton.index("## 市场格局结论")

    def test_no_details_blob(self) -> None:
        """骨架不倾倒 details blob（结构化事实由 pricing 表 + writer 解读承担）。"""
        skeleton = MarkdownRenderer().render_skeleton(_report())
        assert "明细:" not in skeleton
        assert "```" not in skeleton

    def test_pricing_table_retained(self) -> None:
        """断言性内容（定价表）100% 代码渲染，不经 LLM。"""
        skeleton = MarkdownRenderer().render_skeleton(_report())
        assert "#### 定价档位" in skeleton
        assert "| pro | Pro | $20 |" in skeleton

    def test_h1_meta_block_matches_render(self) -> None:
        report = _report()
        renderer = MarkdownRenderer()
        skeleton = renderer.render_skeleton(report)
        for line in (
            "# cursor 竞品分析报告",
            "> 生成时间: 2026-09-10T00:00:00+00:00",
            "> 终态: `success`",
            "> 综合置信度: **0.70**",
        ):
            assert line in skeleton

    def test_show_gaps_section(self) -> None:
        report = _report()
        report.gaps_pending = [InfoGap(field="roadmap", priority=5)]
        skeleton = MarkdownRenderer().render_skeleton(report, show_gaps=True)
        assert "## 未关闭缺口" in skeleton
        assert "**roadmap**" in skeleton
        # 缺口段在市场格局结论之前
        assert skeleton.index("## 未关闭缺口") < skeleton.index("## 市场格局结论")
        # 默认关闭
        assert "## 未关闭缺口" not in MarkdownRenderer().render_skeleton(report)


class TestInjectSlots:
    _SKELETON = (
        "# x 竞品分析报告\n\n{{slot:executive_summary}}\n\n## 维度结论\n\n"
        "{{slot:dimension_insight:pricing}}\n\n## 市场格局结论\n\n{{slot:market_conclusion}}\n"
    )

    def test_full_injection(self) -> None:
        out = inject_slots(
            self._SKELETON,
            {
                "executive_summary": "整体解读。",
                "dimension_insight:pricing": "定价解读。",
                "market_conclusion": "格局结论。",
            },
        )
        assert "整体解读。" in out and "定价解读。" in out and "格局结论。" in out
        assert "{{slot:" not in out

    def test_missing_slot_fallback_notes(self) -> None:
        out = inject_slots(self._SKELETON, {"executive_summary": "整体解读。"})
        assert "（本维度解读暂缺）" in out
        assert "（本节解读暂缺）" in out
        assert "{{slot:" not in out

    def test_blank_prose_treated_as_missing(self) -> None:
        out = inject_slots(self._SKELETON, {"dimension_insight:pricing": "  "})
        assert "（本维度解读暂缺）" in out

    def test_extra_prose_keys_ignored(self) -> None:
        out = inject_slots(self._SKELETON, {"unknown_slot": "不应出现", "executive_summary": "ok"})
        assert "不应出现" not in out

    def test_placeholder_must_own_the_line(self) -> None:
        """行内 {{slot:...}} 文本（如 prose 中的示例）不被替换。"""
        skeleton = "说明：形如 {{slot:executive_summary}} 的占位独占一行才生效\n"
        assert inject_slots(skeleton, {"executive_summary": "x"}) == skeleton

    def test_roundtrip_skeleton_inject(self) -> None:
        """render_skeleton → inject_slots 全链路：无占位残留、表格完好。"""
        report = _report()
        renderer = MarkdownRenderer()
        skeleton = renderer.render_skeleton(report)
        out = inject_slots(skeleton, {})  # 全部降级
        assert "{{slot:" not in out
        assert "#### 定价档位" in out
        assert out.count("（本维度解读暂缺）") == 2
        assert out.count("（本节解读暂缺）") == 2
