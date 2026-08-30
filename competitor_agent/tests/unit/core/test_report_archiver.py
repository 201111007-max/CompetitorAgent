"""report_archiver 单测（设计文档 22 §5 落盘）：
原子写 reports/competitor/<竞品>.md、默认 output_dir 取自 config、父目录自动创建、
重复写原子替换、空报告拒绝、路径穿越净化。"""
from __future__ import annotations

from pathlib import Path

import pytest

from competitor_agent.config.loader import AppConfig
from competitor_agent.core import report_archiver as ra
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.report import ComparisonReport, CompetitorReport


def _report(name: str = "cursor", markdown: str = "# cursor 竞品分析报告\n正文") -> CompetitorReport:
    return CompetitorReport(
        competitor=Competitor(name=name),
        markdown_report=markdown,
        terminal_state="done",
    )


class TestSaveReportMarkdown:
    def test_writes_file_with_report_content(self, tmp_path: Path) -> None:
        path = ra.save_report_markdown(_report(), output_dir=tmp_path)
        assert path == tmp_path / "cursor.md"
        assert path.read_text(encoding="utf-8") == "# cursor 竞品分析报告\n正文"

    def test_default_output_dir_from_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = AppConfig()
        cfg.report.output_dir = str(tmp_path / "reports" / "competitor")
        monkeypatch.setattr(ra, "load_config", lambda: cfg)
        # 设计文档 70：resolve_output_dir 优先级 settings > yaml；隔离真实 settings.json
        monkeypatch.setattr(ra, "get_setting", lambda *a, **k: "")
        path = ra.save_report_markdown(_report())
        assert path.exists()
        assert path.parent == tmp_path / "reports" / "competitor"

    def test_parent_dirs_auto_created(self, tmp_path: Path) -> None:
        path = ra.save_report_markdown(_report(), output_dir=tmp_path / "a" / "b" / "c")
        assert path.exists()

    def test_atomic_overwrite_replaces_content(self, tmp_path: Path) -> None:
        ra.save_report_markdown(_report(markdown="v1"), output_dir=tmp_path)
        ra.save_report_markdown(_report(markdown="v2"), output_dir=tmp_path)
        assert (tmp_path / "cursor.md").read_text(encoding="utf-8") == "v2"

    def test_empty_report_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            ra.save_report_markdown(_report(markdown=""), output_dir=tmp_path)

    def test_path_traversal_sanitized(self, tmp_path: Path) -> None:
        path = ra.save_report_markdown(_report(name="../../evil"), output_dir=tmp_path)
        assert path.parent == tmp_path
        assert ".." not in path.name

    def test_comparison_report_saved(self, tmp_path: Path) -> None:
        comp = ComparisonReport(
            competitors=[Competitor(name="Cursor"), Competitor(name="Windsurf")],
            markdown_report="# 对比矩阵",
        )
        path = ra.save_report_markdown(comp, output_dir=tmp_path)
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "# 对比矩阵"


class TestReportFilePath:
    def test_matches_saved_filename(self, tmp_path: Path) -> None:
        ra.save_report_markdown(_report(), output_dir=tmp_path)
        assert ra.report_file_path("cursor", output_dir=tmp_path).exists()

    def test_missing_returns_path_without_file(self, tmp_path: Path) -> None:
        p = ra.report_file_path("cursor", output_dir=tmp_path)
        assert not p.exists()


class TestResolveComparisonDir:
    """设计文档 70 §8.2 D2a：对比目录恒派生自 resolve_output_dir 的 /comparison。"""

    def test_derives_from_default_output(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(ra, "get_setting", lambda *a, **k: "")
        # 默认 output_dir → <项目根>/output，comparison 为其子目录
        base = ra.resolve_output_dir(None)
        assert ra.resolve_comparison_dir() == base / "comparison"

    def test_derives_from_explicit_dir(self, tmp_path: Path) -> None:
        assert ra.resolve_comparison_dir(tmp_path) == tmp_path / "comparison"

    def test_parent_dir_net_added_endswith_comparison(self, tmp_path: Path) -> None:
        d = ra.resolve_comparison_dir(tmp_path)
        assert d.name == "comparison"
        assert d.parent == tmp_path
