"""问题 8 Web 安全：CORS 收紧 + API Token 认证

- require_auth：未配置 token 时放行（本地开发）；配置后校验 Bearer 或 ?token=。
- CORS：allow_origins 收紧为配置的受信来源，而非 "*"。
"""
from __future__ import annotations

import pytest
from competitor_agent import web_app
from competitor_agent.config.loader import AppConfig, SecurityConfig
from fastapi import HTTPException


class _FakeRequest:
    """最小 Request 替身：仅暴露 headers"""

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}


def _call_require_auth(token: str = "", auth_header: str = "") -> None:
    req = _FakeRequest({"Authorization": auth_header} if auth_header else {})
    web_app.require_auth(req, token=token)


def test_auth_passes_when_no_token_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """未配置 token 时（本地开发）所有请求放行。"""
    monkeypatch.setattr(web_app._config.security, "auth_token", "")
    _call_require_auth()  # 不应抛异常


def test_auth_rejects_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """配置 token 后，无凭据请求返回 401。"""
    monkeypatch.setattr(web_app._config.security, "auth_token", "secret-token")
    with pytest.raises(HTTPException) as exc:
        _call_require_auth()
    assert exc.value.status_code == 401


def test_auth_rejects_wrong_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    """错误 Bearer token 返回 401。"""
    monkeypatch.setattr(web_app._config.security, "auth_token", "secret-token")
    with pytest.raises(HTTPException) as exc:
        _call_require_auth(auth_header="Bearer wrong-token")
    assert exc.value.status_code == 401


def test_auth_accepts_correct_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    """正确 Bearer token 通过。"""
    monkeypatch.setattr(web_app._config.security, "auth_token", "secret-token")
    _call_require_auth(auth_header="Bearer secret-token")  # 不应抛异常


def test_auth_accepts_query_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """正确 ?token= 查询参数通过（EventSource 无法设置 Header）。"""
    monkeypatch.setattr(web_app._config.security, "auth_token", "secret-token")
    _call_require_auth(token="secret-token")  # 不应抛异常


def test_cors_origins_tightened(monkeypatch: pytest.MonkeyPatch) -> None:
    """CORS 仅允许配置的受信来源，而非 "*"。"""
    monkeypatch.setattr(
        web_app._config.security,
        "cors_origins",
        ["http://localhost:8000"],
    )
    # 通过 FastAPI 应用读取中间件配置
    cors = next(
        m for m in web_app.app.user_middleware if m.cls.__name__ == "CORSMiddleware"
    )
    assert cors.kwargs["allow_origins"] == ["http://localhost:8000"]
    assert "*" not in cors.kwargs["allow_origins"]


def test_security_config_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """auth_token 从环境变量 COMPETITOR_AUTH_TOKEN 读取，不明文落码。"""
    from competitor_agent.config.loader import load_config

    monkeypatch.setenv("COMPETITOR_AUTH_TOKEN", "env-secret")
    cfg = load_config()
    assert cfg.security.auth_token == "env-secret"
    assert cfg.security.cors_origins == ["http://localhost:8000"]


def test_security_config_defaults() -> None:
    """AppConfig 默认 security 配置：localhost 来源 + 空 token。"""
    cfg = AppConfig()
    assert cfg.security.cors_origins == ["http://localhost:8000"]
    assert cfg.security.auth_token == ""
    assert isinstance(cfg.security, SecurityConfig)
