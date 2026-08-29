"""设计文档 70 Part B — Web 报告目录设置与下载端点单测。

覆盖：
① GET /api/settings：当前生效值 + data_dir + 默认值（未设置 → 项目默认）；
② PUT /api/settings：写入 settings.json（合并）、传 "" 重置、非法请求体 400；
③ 下载端点读 download 目录（download_file_path）并返回 attachment。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from competitor_agent import web_app
from competitor_agent.core import report_settings as rs
from fastapi.testclient import TestClient


def _patch_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    out, dl = Path("D:/proj/output"), Path("D:/proj/download")
    monkeypatch.setattr(rs, "default_output_dir", lambda: out)
    monkeypatch.setattr(rs, "default_download_dir", lambda: dl)
    monkeypatch.setattr(web_app, "resolve_output_dir", lambda *a, **k: out)
    monkeypatch.setattr(web_app, "resolve_download_dir", lambda *a, **k: dl)
    monkeypatch.setattr(rs, "settings_path", lambda: Path("D:/data/settings.json"))
    monkeypatch.setattr(web_app, "get_setting", lambda k: "")


class TestSettingsEndpoints:
    def test_get_returns_defaults_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_defaults(monkeypatch)
        with TestClient(web_app.app) as client:
            resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["report_output_dir"] == str(Path("D:/proj/output"))
        assert data["report_download_dir"] == str(Path("D:/proj/download"))
        assert data["data_dir"] == str(Path("D:/data"))
        assert data["defaults"]["report_output_dir"] == str(Path("D:/proj/output"))
        assert data["defaults"]["report_download_dir"] == str(Path("D:/proj/download"))

    def test_get_returns_effective_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_defaults(monkeypatch)
        monkeypatch.setattr(
            web_app, "get_setting",
            lambda k: "D:/custom/out" if k == "report_output_dir" else "D:/custom/dl",
        )
        with TestClient(web_app.app) as client:
            resp = client.get("/api/settings")
        data = resp.json()
        assert data["report_output_dir"] == "D:/custom/out"
        assert data["report_download_dir"] == "D:/custom/dl"

    def test_put_writes_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_defaults(monkeypatch)
        written: dict[str, str] = {}

        def fake_write(updates: dict[str, str]) -> dict[str, str]:
            written.update(updates)
            return written

        monkeypatch.setattr("competitor_agent.core.report_settings.write_settings", fake_write)
        monkeypatch.setattr(
            web_app, "get_setting",
            lambda k: written.get(k, ""),
        )
        with TestClient(web_app.app) as client:
            resp = client.put(
                "/api/settings",
                json={"report_output_dir": "D:/reports", "report_download_dir": "D:/downloads"},
            )
        assert resp.status_code == 200
        assert written == {"report_output_dir": "D:/reports", "report_download_dir": "D:/downloads"}
        data = resp.json()
        assert data["report_output_dir"] == "D:/reports"

    def test_put_empty_resets_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_defaults(monkeypatch)
        written: dict[str, str] = {}

        def fake_write(updates: dict[str, str]) -> dict[str, str]:
            written.update({k: v for k, v in updates.items() if v})
            return written

        monkeypatch.setattr("competitor_agent.core.report_settings.write_settings", fake_write)
        monkeypatch.setattr(web_app, "get_setting", lambda k: written.get(k, ""))
        with TestClient(web_app.app) as client:
            resp = client.put("/api/settings", json={"report_output_dir": "", "report_download_dir": ""})
        assert resp.status_code == 200
        assert written == {}
        assert resp.json()["report_output_dir"] == str(Path("D:/proj/output"))  # 重置 → 默认

    def test_put_value_equal_to_default_stores_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """值等于项目默认目录（含斜杠/大小写差异）→ 存空串，不固化绝对路径。"""
        _patch_defaults(monkeypatch)
        written: dict[str, str] = {}

        def fake_write(updates: dict[str, str]) -> dict[str, str]:
            written.update(updates)
            return written

        monkeypatch.setattr("competitor_agent.core.report_settings.write_settings", fake_write)
        monkeypatch.setattr(web_app, "get_setting", lambda k: written.get(k, ""))
        with TestClient(web_app.app) as client:
            resp = client.put(
                "/api/settings",
                json={"report_output_dir": "d:\\PROJ\\output", "report_download_dir": "D:/proj/download"},
            )
        assert resp.status_code == 200
        assert written["report_output_dir"] == ""
        assert written["report_download_dir"] == ""

    def test_put_custom_path_stored_as_is(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_defaults(monkeypatch)
        written: dict[str, str] = {}

        def fake_write(updates: dict[str, str]) -> dict[str, str]:
            written.update(updates)
            return written

        monkeypatch.setattr("competitor_agent.core.report_settings.write_settings", fake_write)
        monkeypatch.setattr(web_app, "get_setting", lambda k: written.get(k, ""))
        with TestClient(web_app.app) as client:
            resp = client.put(
                "/api/settings",
                json={"report_output_dir": "D:/custom/out", "report_download_dir": "D:/custom/dl"},
            )
        assert resp.status_code == 200
        assert written == {"report_output_dir": "D:/custom/out", "report_download_dir": "D:/custom/dl"}

    def test_put_invalid_body_400(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_defaults(monkeypatch)
        with TestClient(web_app.app) as client:
            resp = client.put("/api/settings", content="not json", headers={"Content-Type": "application/json"})
        assert resp.status_code == 400


class TestDownloadEndpoint:
    def test_download_reads_download_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        dl = tmp_path / "dl"
        dl.mkdir()
        (dl / "cursor.md").write_text("# cursor 竞品分析报告\n下载副本", encoding="utf-8")
        monkeypatch.setattr(web_app, "download_file_path", lambda c, **kw: dl / "cursor.md")
        with TestClient(web_app.app) as client:
            resp = client.get("/api/reports/cursor/download")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert "# cursor 竞品分析报告" in resp.text

    def test_download_missing_404(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(web_app, "download_file_path", lambda c, **kw: tmp_path / "none.md")
        with TestClient(web_app.app) as client:
            resp = client.get("/api/reports/cursor/download")
        assert resp.status_code == 404
