"""§14 日志完善 Web 端点：/api/logs/{session_id} + /api/logs/stream/{session_id}

- /api/logs/{sid} 返回结构化会话日志（tail 限定最近 N 行）。
- auth 未配置放行；配置后无凭据 401，正确 token 通过。
- /api/logs/stream/{sid} SSE 推送日志尾部追加，会话结束后发 log_end。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from competitor_agent import web_app
from competitor_agent.observability import logger as L
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_logging(tmp_path: Path) -> Path:
    log_dir = tmp_path / "logs"
    L.setup_logging(level="INFO", log_dir=log_dir, json_format=True)
    L._session_adapters.clear()
    yield log_dir
    root = logging.getLogger("competitor_agent")
    for h in list(root.handlers):
        root.removeHandler(h)
    L._configured = False
    L.set_current_session(None)


def _write_sample_log(sid: str) -> None:
    slog = L.get_session_logger(sid)
    for i in range(3):
        L.log_event(slog, "collect.done", "collect", f"采集完成 {i}", url=f"https://a{i}.com", i=i)
    L.close_session_log(sid)


class TestLogsEndpoint:
    def test_logs_returns_session_lines(self) -> None:
        _write_sample_log("sess_web_logs")
        with TestClient(web_app.app) as client:
            resp = client.get("/api/logs/sess_web_logs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess_web_logs"
        assert data["count"] == 3
        assert data["lines"][0]["event"] == "collect.done"
        assert data["lines"][0]["url"] == "https://a0.com"

    def test_logs_tail_limits_lines(self) -> None:
        _write_sample_log("sess_web_tail")
        with TestClient(web_app.app) as client:
            resp = client.get("/api/logs/sess_web_tail", params={"tail": 2})
        data = resp.json()
        assert data["count"] == 2
        assert data["lines"][-1]["i"] == 2

    def test_logs_missing_session_returns_empty(self) -> None:
        with TestClient(web_app.app) as client:
            resp = client.get("/api/logs/sess_not_exist")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["lines"] == []


class TestLogsAuth:
    def test_logs_unauthorized_when_token_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(web_app._config.security, "auth_token", "secret-token")
        with TestClient(web_app.app) as client:
            resp = client.get("/api/logs/sess_x")
        assert resp.status_code == 401

    def test_logs_accepts_correct_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(web_app._config.security, "auth_token", "secret-token")
        with TestClient(web_app.app) as client:
            resp = client.get("/api/logs/sess_x", headers={"Authorization": "Bearer secret-token"})
        assert resp.status_code == 200

    def test_logs_accepts_query_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(web_app._config.security, "auth_token", "secret-token")
        with TestClient(web_app.app) as client:
            resp = client.get("/api/logs/sess_x", params={"token": "secret-token"})
        assert resp.status_code == 200


class TestLogsStream:
    def test_stream_ends_with_log_end_after_session_removed(self) -> None:
        """会话日志流：尾部追加推送，会话结束后发 log_end 收尾。"""
        _write_sample_log("sess_web_stream")
        with TestClient(web_app.app) as client, client.stream("GET", "/api/logs/stream/sess_web_stream") as resp:
                assert resp.status_code == 200
                body = "".join(resp.iter_text())
        lines = [json.loads(b[len("data: "):]) for b in body.splitlines() if b.startswith("data: ")]
        assert any(ln["event"] == "collect.done" for ln in lines)
        assert any(ln["event"] == "log_end" and ln["session_id"] == "sess_web_stream" for ln in lines)
