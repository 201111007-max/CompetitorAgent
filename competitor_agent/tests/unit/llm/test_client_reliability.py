"""LLMClient 可靠性测试（设计文档 36：重试 / 多模型 fallback / 超时）

覆盖：可重试错误退避重试、不可重试错误直接抛、fallback 链、全灭抛
LLMUnavailableError、超时计入重试、LLMConfig 解析与默认值叠加。
"""
from __future__ import annotations

import pytest
from competitor_agent.config.loader import LLMConfig, load_config
from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.llm.client import LLMClient


class FakeStatusError(Exception):
    """带 HTTP 状态码的伪 SDK 错误（模拟 openai APIStatusError.status_code）"""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


def _capture_log(monkeypatch, client: LLMClient) -> dict:
    logged: dict = {}
    monkeypatch.setattr(client, "_log_call", lambda *a, **kw: logged.update(kw))
    return logged


class TestRetryBackoff:
    def test_retry_then_success(self, monkeypatch) -> None:
        calls = {"n": 0}

        def call_func(messages, model=None):
            calls["n"] += 1
            if calls["n"] < 3:
                raise FakeStatusError(429)
            return "ok"

        client = LLMClient(call_func=call_func, max_retries=3, backoff=0)
        logged = _capture_log(monkeypatch, client)
        assert client.complete([{"role": "user", "content": "hi"}]) == "ok"
        assert calls["n"] == 3
        assert logged["attempts"] == 3
        assert logged["retried"] is True
        assert logged["timed_out"] is False

    def test_exhaust_retries_raises_unavailable(self) -> None:
        calls = {"n": 0}

        def call_func(messages, model=None):
            calls["n"] += 1
            raise FakeStatusError(503)

        client = LLMClient(call_func=call_func, max_retries=3, backoff=0)
        with pytest.raises(LLMUnavailableError):
            client.complete([{"role": "user", "content": "hi"}])
        assert calls["n"] == 3

    def test_complete_json_uses_retrying_complete(self) -> None:
        calls = {"n": 0}

        def call_func(messages, model=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise FakeStatusError(429)
            return '{"ok": true}'

        client = LLMClient(call_func=call_func, max_retries=3, backoff=0)
        assert client.complete_json([{"role": "user", "content": "hi"}]) == {"ok": True}
        assert calls["n"] == 2


class TestNonRetryable:
    def test_401_raises_immediately_without_retry(self) -> None:
        calls = {"n": 0}

        def call_func(messages, model=None):
            calls["n"] += 1
            raise FakeStatusError(401)

        client = LLMClient(call_func=call_func, max_retries=3, backoff=0)
        with pytest.raises(FakeStatusError):
            client.complete([{"role": "user", "content": "hi"}])
        assert calls["n"] == 1

    def test_generic_error_not_retried(self) -> None:
        calls = {"n": 0}

        def call_func(messages, model=None):
            calls["n"] += 1
            raise ValueError("bad request")

        client = LLMClient(call_func=call_func, max_retries=3, backoff=0)
        with pytest.raises(ValueError):
            client.complete([{"role": "user", "content": "hi"}])
        assert calls["n"] == 1


class TestFallbackChain:
    def test_fallback_model_success(self, monkeypatch) -> None:
        seen_models: list[str] = []

        def call_func(messages, model=None):
            seen_models.append(model)
            if model == "main":
                raise FakeStatusError(429)
            return "fallback-ok"

        client = LLMClient(
            call_func=call_func, model="main", fallback_models=["backup1"], max_retries=1, backoff=0
        )
        logged = _capture_log(monkeypatch, client)
        assert client.complete([{"role": "user", "content": "hi"}]) == "fallback-ok"
        assert seen_models == ["main", "backup1"]
        assert logged["final_model"] == "backup1"
        assert logged["retried"] is True

    def test_all_models_exhausted_raises(self) -> None:
        seen_models: list[str] = []

        def call_func(messages, model=None):
            seen_models.append(model)
            raise FakeStatusError(429)

        client = LLMClient(
            call_func=call_func, model="main", fallback_models=["backup1", "backup2"],
            max_retries=1, backoff=0,
        )
        with pytest.raises(LLMUnavailableError):
            client.complete([{"role": "user", "content": "hi"}])
        assert seen_models == ["main", "backup1", "backup2"]


class TestTimeout:
    def test_timeout_error_retried_and_flagged(self, monkeypatch) -> None:
        calls = {"n": 0}

        def call_func(messages, model=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("read timeout")
            return "ok"

        client = LLMClient(call_func=call_func, max_retries=3, backoff=0)
        logged = _capture_log(monkeypatch, client)
        assert client.complete([{"role": "user", "content": "hi"}]) == "ok"
        assert calls["n"] == 2
        assert logged["attempts"] == 2
        assert logged["timed_out"] is True


class TestConfig:
    def test_llm_config_defaults(self) -> None:
        cfg = LLMConfig()
        assert cfg.fallback_models == []
        assert cfg.timeout is None
        assert cfg.max_retries == 3

    def test_load_config_llm_section(self, tmp_path) -> None:
        cfg_path = tmp_path / "cfg.yaml"
        cfg_path.write_text(
            "model: legacy\n"
            "llm:\n"
            "  model: main-m\n"
            "  api_base_url: http://x\n"
            "  fallback_models: [a, b]\n"
            "  timeout: 42\n"
            "  max_retries: 5\n",
            encoding="utf-8",
        )
        cfg = load_config(cfg_path)
        assert cfg.llm.model == "main-m"
        assert cfg.llm.api_base_url == "http://x"
        assert cfg.llm.fallback_models == ["a", "b"]
        assert cfg.llm.timeout == 42
        assert cfg.llm.max_retries == 5
        assert cfg.model == "legacy"  # 顶层兼容字段不受影响

    def test_load_config_llm_section_defaults_merge(self, tmp_path) -> None:
        cfg_path = tmp_path / "cfg.yaml"
        cfg_path.write_text("llm: {}\n", encoding="utf-8")
        cfg = load_config(cfg_path)
        assert cfg.llm.fallback_models == []
        assert cfg.llm.timeout is None
        assert cfg.llm.max_retries == 3
