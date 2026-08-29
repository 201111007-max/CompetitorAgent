"""core/report_builder.py + markdown_renderer.py 单测"""
from competitor_agent.core.markdown_renderer import MarkdownRenderer
from competitor_agent.core.report_builder import ReportBuilder
from competitor_agent.domain_types import (
    ComparisonReport,
    Competitor,
    DimensionResult,
    GapStatus,
    InfoGap,
    ResultStatus,
    SourceEvidence,
)


def _result(dimension, confidence=0.8, status=ResultStatus.COMPLETE, summary="结论", evidence=None):
    return DimensionResult(
        dimension=dimension,
        summary=summary,
        details={"key": "val"},
        confidence=confidence,
        evidence=evidence or [SourceEvidence(source_name="docs", url="https://x.com", content_hash="h")],
        status=status,
    )


class TestReportBuilder:
    def test_build_basic(self):
        b = ReportBuilder()
        comp = Competitor(name="cursor")
        results = [_result("pricing", 0.8), _result("feature", 0.9)]
        pending = []

        report = b.build(comp, results, pending, "success")
        assert report.competitor.name == "cursor"
        assert len(report.dimension_results) == 2
        assert report.markdown_report  # Markdown 已生成

    def test_aggregate_weighted_confidence(self):
        b = ReportBuilder()
        comp = Competitor(name="cursor")
        # pricing=0.8(w0.25), feature=0.9(w0.25)
        results = [_result("pricing", 0.8), _result("feature", 0.9)]
        report = b.build(comp, results, [], "success")
        assert 0.8 < report.overall_confidence < 0.9

    def test_build_no_results(self):
        b = ReportBuilder()
        report = b.build(Competitor(name="x"), [], [], "partial")
        assert report.overall_confidence == 0.0
        assert report.markdown_report


class TestMarkdownRenderer:
    def test_render_contains_sections(self):
        b = ReportBuilder()
        comp = Competitor(name="cursor")
        results = [_result("pricing", 0.85, summary="Pro $20/mo")]
        pending = [InfoGap(field="roadmap", priority=4, confidence=0.1, status=GapStatus.OPEN)]
        report = b.build(comp, results, pending, "success")
        md = report.markdown_report

        assert "# cursor 竞品分析报告" in md
        assert "## 维度结论" in md
        assert "Pro $20/mo" in md
        # 设计文档 66 §3.4：默认不渲染"未关闭缺口"段（gaps_pending 数据仍在报告对象）
        assert "## 未关闭缺口" not in md
        assert report.gaps_pending[0].field == "roadmap"

    def test_render_show_gaps_renders_section(self):
        b = ReportBuilder()
        report = b.build(
            Competitor(name="x"),
            [_result("pricing", 0.6, status=ResultStatus.PARTIAL)],
            [InfoGap(field="sentiment", priority=5, status=GapStatus.OPEN)],
            "partial",
        )
        # 默认不渲染；show_gaps=True 渲染（CLI/导出侧显式开启）
        assert "## 未关闭缺口" not in report.markdown_report
        md = MarkdownRenderer().render(report, show_gaps=True)
        assert "## 未关闭缺口" in md
        assert "sentiment" in md
        assert "partial" in report.markdown_report

    def test_render_no_pending(self):
        b = ReportBuilder()
        report = b.build(Competitor(name="x"), [_result("pricing", 0.8)], [], "success")
        assert "全部缺口已关闭" not in report.markdown_report
        md = MarkdownRenderer().render(report, show_gaps=True)
        assert "全部缺口已关闭" in md


class TestBuildComparison:
    def _single_report(self, name, results):
        b = ReportBuilder()
        return b.build(Competitor(name=name), results, [], "success")

    def test_build_comparison_matrix_columns(self):
        b = ReportBuilder()
        r1 = self._single_report("cursor", [_result("pricing", 0.8), _result("feature", 0.9)])
        r2 = self._single_report("windsurf", [_result("pricing", 0.7)])
        comp = b.build_comparison([r1, r2])
        assert isinstance(comp, ComparisonReport)
        assert len(comp.reports) == 2
        md = comp.markdown_report
        assert "cursor" in md and "windsurf" in md
        assert "品类格局矩阵" in md
        assert "pricing" in md and "feature" in md

    def test_render_comparison_best_per_dim(self):
        b = ReportBuilder()
        r1 = self._single_report("cursor", [_result("pricing", 0.9)])
        r2 = self._single_report("windsurf", [_result("pricing", 0.6)])
        comp = b.build_comparison([r1, r2])
        md = comp.markdown_report
        # 每维度最佳应为置信度更高的 cursor
        assert "**cursor**" in md

    def test_render_comparison_missing_dimension_n_a(self):
        b = ReportBuilder()
        r1 = self._single_report("cursor", [_result("pricing", 0.9)])
        r2 = self._single_report("windsurf", [])
        comp = b.build_comparison([r1, r2])
        md = comp.markdown_report
        assert "N/A" in md

    def test_render_comparison_ranking(self):
        b = ReportBuilder()
        r1 = self._single_report("cursor", [_result("pricing", 0.9)])
        r2 = self._single_report("windsurf", [_result("pricing", 0.5)])
        comp = b.build_comparison([r1, r2])
        md = comp.markdown_report
        # 汇总排名 cursor 在前
        assert md.index("cursor") < md.index("windsurf")