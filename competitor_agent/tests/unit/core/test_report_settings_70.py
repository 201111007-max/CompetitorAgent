"""设计文档 70 Part B — 报告目录运行时配置单测。

覆盖：
① `report_settings`：project_dir/default_output_dir/default_download_dir 派生、
   settings.json 读写（缺文件/坏 JSON 空 dict、原子写、合并保留未涉及键）；
② `resolve_output_dir` 优先级：显式 > settings > yaml > 项目默认；
③ `resolve_download_dir`：settings 覆盖 / 默认项目 download；
④ `save_report_download` 落盘、`download_file_path` 回退链（download → output → 旧归档）、
   `report_file_path` 旧归档读侧回退（显式 dir 不回退）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from competitor_agent.config.loader import AppConfig
from competitor_agent.core import report_archiver as ra
from competitor_agent.core import report_settings as rs
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.report import CompetitorReport


def _report(name: str = "cursor", markdown: str = "# cursor 竞品分析报告\n正文") -> CompetitorReport:
    return CompetitorReport(
        competitor=Competitor(name=name), markdown_report=markdown, terminal_state="done"
    )


def _patch_output(monkeypatch: pytest.MonkeyPatch, out: str, settings: str = "") -> None:
    cfg = AppConfig()
    cfg.report.output_dir = out
    monkeypatch.setattr(ra, "load_config", lambda: cfg)
    monkeypatch.setattr(ra, "get_setting", lambda k: settings if k == "report_output_dir" else "")


class TestReportSettings:
    def test_project_dir_is_repo_root(self) -> None:
        assert rs.project_dir() == Path(__file__).resolve().parents[4]
        assert (rs.project_dir() / "competitor_agent").exists()

    def test_defaults_under_project(self) -> None:
        assert rs.default_output_dir() == rs.project_dir() / "output"
        assert rs.default_download_dir() == rs.project_dir() / "download"

    def test_read_missing_returns_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(rs, "settings_path", lambda: tmp_path / "settings.json")
        assert rs.read_settings() == {}

    def test_read_corrupt_returns_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        p = tmp_path / "settings.json"
        p.write_text("not json{{", encoding="utf-8")
        monkeypatch.setattr(rs, "settings_path", lambda: p)
        assert rs.read_settings() == {}

    def test_write_then_read_roundtrip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        p = tmp_path / "settings.json"
        monkeypatch.setattr(rs, "settings_path", lambda: p)
        rs.write_settings({"report_output_dir": "D:/reports", "unknown_key": "ignored"})
        assert rs.read_settings() == {"report_output_dir": "D:/reports"}
        assert "unknown_key" not in rs.read_settings()

    def test_write_merges_keeps_unset_key(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        p = tmp_path / "settings.json"
        monkeypatch.setattr(rs, "settings_path", lambda: p)
        rs.write_settings({"report_output_dir": "D:/out"})
        rs.write_settings({"report_download_dir": "D:/dl"})
        data = rs.read_settings()
        assert data == {"report_output_dir": "D:/out", "report_download_dir": "D:/dl"}


class TestResolveOutputDir:
    def test_explicit_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_output(monkeypatch, "D:/yaml/out", settings="D:/settings/out")
        assert ra.resolve_output_dir(tmp_path) == tmp_path

    def test_settings_over_yaml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_output(monkeypatch, "D:/yaml/out", settings="D:/settings/out")
        assert ra.resolve_output_dir() == Path("D:/settings/out")

    def test_yaml_used_when_settings_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_output(monkeypatch, "D:/yaml/out")
        assert ra.resolve_output_dir() == Path("D:/yaml/out")

    def test_yaml_empty_falls_back_to_project_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = AppConfig()
        cfg.report.output_dir = ""
        monkeypatch.setattr(ra, "load_config", lambda: cfg)
        monkeypatch.setattr(ra, "get_setting", lambda *a, **k: "")
        assert ra.resolve_output_dir() == rs.default_output_dir()


class TestResolveDownloadDir:
    def test_default_project_download(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ra, "get_setting", lambda k: "")
        assert ra.resolve_download_dir() == rs.default_download_dir()

    def test_settings_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ra, "get_setting", lambda k: "D:/dl" if k == "report_download_dir" else "")
        assert ra.resolve_download_dir() == Path("D:/dl")


class TestDownloadWriteAndFallback:
    def test_save_report_download_writes(self, tmp_path: Path) -> None:
        path = ra.save_report_download(_report(), download_dir=tmp_path)
        assert path == tmp_path / "cursor.md"
        assert path.read_text(encoding="utf-8") == "# cursor 竞品分析报告\n正文"

    def test_download_file_path_prefers_download_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dl = tmp_path / "dl"
        dl.mkdir()
        (dl / "cursor.md").write_text("x", encoding="utf-8")
        monkeypatch.setattr(ra, "resolve_download_dir", lambda: dl)
        monkeypatch.setattr(ra, "resolve_output_dir", lambda *a, **k: tmp_path / "out")
        assert ra.download_file_path("cursor") == dl / "cursor.md"

    def test_download_file_path_falls_back_to_output(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        out.mkdir()
        (out / "cursor.md").write_text("x", encoding="utf-8")
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(ra, "resolve_download_dir", lambda: tmp_path / "dl")
        monkeypatch.setattr(ra, "resolve_output_dir", lambda *a, **k: out)
        monkeypatch.setattr(ra, "get_setting", lambda *a, **k: "")
        try:
            assert ra.download_file_path("cursor") == out / "cursor.md"
        finally:
            monkeypatch.undo()

    def test_report_file_path_legacy_fallback_when_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 始终把旧归档目录重定向到 tmp（绝不触碰真实 ~/.competitor_agent 数据）
        legacy = tmp_path / "legacy"
        monkeypatch.setattr(ra, "_LEGACY_REPORTS_DIR", legacy)
        legacy.mkdir(parents=True, exist_ok=True)
        (legacy / "cursor.md").write_text("legacy", encoding="utf-8")
        monkeypatch.setattr(ra, "get_setting", lambda *a, **k: "")
        cfg = AppConfig()
        cfg.report.output_dir = ""  # yaml 空 → 项目默认（不存在）→ 走旧归档回退
        monkeypatch.setattr(ra, "load_config", lambda: cfg)
        assert ra.report_file_path("cursor") == legacy / "cursor.md"

    def test_report_file_path_explicit_dir_skips_legacy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        (legacy / "cursor.md").write_text("legacy", encoding="utf-8")
        monkeypatch.setattr(ra, "_LEGACY_REPORTS_DIR", legacy)
        assert ra.report_file_path("cursor", output_dir=tmp_path) == tmp_path / "cursor.md"
        assert not (tmp_path / "cursor.md").exists()
