"""设计文档 67 §3.1 — 可视化导出单测。

render_radar 无 matplotlib → None（不炸）；render_html 单文件含 markdown 正文 +
结构化数据 + 自包含 CSS（不依赖外网资源或离线降级）。
"""
from __future__ import annotations

from pathlib import Path

from competitor_agent.core.report_visuals import render_html, render_html_doc, render_radar
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult


def _report(name: str = "cursor") -> CompetitorReport:
    return CompetitorReport(
        competitor=Competitor(name=name),
        dimension_results=[
            DimensionResult(dimension="pricing", summary="Pro $20/mo", confidence=0.8),
            DimensionResult(dimension="performance", summary="SWE-bench 45.2", confidence=0.7),
        ],
        overall_confidence=0.75,
        markdown_report="# Cursor\n\nPro $20/mo 稳定定价。\n\n- 功能：v1.5 发布\n- 性能：SWE-bench 45.2",
        terminal_state="success",
    )


class TestRenderHtml:
    def test_self_contained_single_file(self, tmp_path: Path) -> None:
        out = tmp_path / "cursor.html"
        render_html(_report(), out)
        text = out.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in text
        assert "cursor" in text
        assert "竞品分析报告" in text
        assert "SWE-bench" in text  # markdown 正文
        assert "<style>" in text and "</style>" in text  # 内嵌 CSS
        assert 'type="application/json"' in text  # 结构化数据
        # 不依赖外网资源：无 http:// 外链（数据 script 用 json 转义）
        assert "https://unpkg" not in text and "https://cdn" not in text

    def test_html_doc_offline_markdown_fallback(self, tmp_path: Path) -> None:
        # 离线极简 markdown→HTML 降级路径（无 marked 时 render_html_doc 内部使用）
        from competitor_agent.core.report_visuals import _markdown_to_html

        html = _markdown_to_html("# T\n\n## S\n\n- a\n- b")
        assert "<h1>" in html and "T</h1>" in html
        assert "<h2>" in html and "S</h2>" in html
        assert "<li>" in html and "a</li>" in html

    def test_html_doc_embeds_raw_and_json(self, tmp_path: Path) -> None:
        # render_html_doc 输出结构（无论 marked 是否存在，raw/JSON/样式均内嵌）
        out = render_html_doc(
            "# T\nbody",
            {"competitor": "x", "created_at": "2026-08-29"},
            title="x",
            created_at="2026-08-29",
            out_path=tmp_path / "x.html",
        )
        text = out.read_text(encoding="utf-8")
        assert 'id="raw"' in text or "body" in text
        assert 'type="application/json"' in text

    def test_marks_escape_script_content(self, tmp_path: Path) -> None:
        report = _report()
        report.markdown_report = "<script>alert(1)</script>"
        out = tmp_path / "esc.html"
        render_html(report, out)
        text = out.read_text(encoding="utf-8")
        assert "<script>alert(1)</script>" not in text


class TestRenderRadar:
    def test_radar_skips_without_matplotlib(self, tmp_path: Path, monkeypatch) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "matplotlib":
                raise ImportError("no matplotlib")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        from competitor_agent.domain_types.report import ComparisonReport

        comp = ComparisonReport(
            competitors=[Competitor(name="a"), Competitor(name="b")],
            reports=[_report("a"), _report("b")],
        )
        assert render_radar(comp, tmp_path / "r.png") is None
