"""LLMClient.stream() 流式分词测试（设计文档 63 §5 / §10.1）

覆盖：注入生成器透传、非生成器 mock 包装单 delta、str/SDK 双形态、
kind 分类（text/thinking）、首块可重试错误重启、不可重试错误上抛、
多模型 fallback 切换、全灭 LLMUnavailableError、空流正常完成。
"""
from __future__ import annotations

import sys
import types

import pytest

from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.llm.client import LLMClient, StreamDelta


def _fake_openai_module(cls: type) -> types.ModuleType:
    """构造伪 ``openai`` 模块：``from openai import OpenAI`` 可解析到 ``cls``。"""
    module = types.ModuleType("openai")
    module.OpenAI = cls
    module.__all__ = ["OpenAI"]
    return module


class FakeStatusError(Exception):
    """带 HTTP 状态码的伪 SDK 错误（模拟 openai APIStatusError.status_code）。"""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


def _deltas(client: LLMClient, messages: list[dict] | None = None) -> list[StreamDelta]:
    return list(client.stream(messages or [{"role": "user", "content": "hi"}]))


def _texts(deltas: list[StreamDelta]) -> str:
    return "".join(d.text for d in deltas if d.kind == "text")


class FakeDelta:
    def __init__(self, content="", reasoning="") -> None:
        self.content = content
        self.reasoning_content = reasoning


class FakeChoice:
    def __init__(self, delta) -> None:
        self.delta = delta


class FakeChunk:
    def __init__(self, deltas: list[FakeDelta]) -> None:
        self.choices = [FakeChoice(d) for d in deltas]


class TestInjectGenerator:
    def test_generator_func_passthrough_text_deltas(self) -> None:
        def gen(messages, model=None):
            yield "你"
            yield "好"
            yield StreamDelta(kind="text", text="！")

        client = LLMClient(call_func=gen)
        deltas = _deltas(client)
        assert _texts(deltas) == "你好！"
        assert all(d.model == client._model for d in deltas)

    def test_generator_func_thinking_and_text(self) -> None:
        def gen(messages, model=None):
            yield StreamDelta(kind="thinking", text="先规划…")
            yield StreamDelta(kind="text", text="分析 Cursor")

        client = LLMClient(call_func=gen)
        deltas = _deltas(client)
        assert [d.kind for d in deltas] == ["thinking", "text"]
        assert deltas[0].text == "先规划…"

    def test_non_generator_mock_wrapped_single_delta(self) -> None:
        client = LLMClient(call_func=lambda messages, model=None: "完整文本")
        deltas = _deltas(client)
        assert _texts(deltas) == "完整文本"
        assert len(deltas) == 1


class TestRetryFallback:
    def test_first_chunk_retry_then_success(self) -> None:
        calls = {"n": 0}

        def gen(messages, model=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise FakeStatusError(429)
            yield "ok"

        client = LLMClient(call_func=gen, max_retries=3, backoff=0)
        assert _texts(_deltas(client)) == "ok"
        assert calls["n"] == 2

    def test_non_retryable_error_raises_unavailable(self) -> None:
        def gen(messages, model=None):
            raise FakeStatusError(400)  # 401/400 不可重试

        client = LLMClient(call_func=gen, max_retries=3, backoff=0)
        with pytest.raises(LLMUnavailableError):
            _deltas(client)

    def test_fallback_model_switch(self) -> None:
        calls = {"n": 0, "models": []}

        def gen(messages, model=None):
            calls["n"] += 1
            calls["models"].append(model)
            raise FakeStatusError(503)

        client = LLMClient(
            call_func=gen,
            model="primary",
            fallback_models=["fb1", "fb2"],
            max_retries=1,
            backoff=0,
        )
        with pytest.raises(LLMUnavailableError):
            _deltas(client)
        # primary 1 次 + fb1 1 次 + fb2 1 次，全灭
        assert calls["models"] == ["primary", "fb1", "fb2"]

    def test_fallback_produces_delta(self) -> None:
        calls = {"n": 0}

        def gen(messages, model=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise FakeStatusError(503)
            yield StreamDelta(kind="text", text="来自 fallback", model=model)

        client = LLMClient(
            call_func=gen, model="primary", fallback_models=["fb"], max_retries=1, backoff=0
        )
        deltas = _deltas(client)
        assert _texts(deltas) == "来自 fallback"
        assert deltas[0].model == "fb"


class TestSdkStream:
    def test_sdk_choice_deltas_kind_split(self, monkeypatch) -> None:
        created = {"stream_used": None, "model": None}

        class FakeCompletions:
            def create(self, *, model=None, messages=None, stream=False, **kw):
                created["stream_used"] = stream
                created["model"] = model
                return iter(
                    [
                        FakeChunk([FakeDelta(content="你", reasoning="想…")]),
                        FakeChunk([FakeDelta(content="好")]),
                    ]
                )

        class FakeChat:
            completions = FakeCompletions()

        class FakeOpenAI:
            def __init__(self, **kwargs) -> None:
                pass

            @property
            def chat(self) -> FakeChat:
                return FakeChat()

        monkeypatch.setitem(sys.modules, "openai", _fake_openai_module(FakeOpenAI))
        client = LLMClient(model="m", api_key="k")
        deltas = _deltas(client)
        assert [(d.kind, d.text) for d in deltas] == [
            ("thinking", "想…"),
            ("text", "你"),
            ("text", "好"),
        ]
        assert created["stream_used"] is True
        assert created["model"] == "m"

    def test_sdk_empty_choices_stream_completes(self, monkeypatch) -> None:
        class FakeCompletions:
            def create(self, **kw):
                return iter([FakeChunk([])])

        class FakeChat:
            completions = FakeCompletions()

        class FakeOpenAI:
            def __init__(self, **kwargs) -> None:
                pass

            @property
            def chat(self) -> FakeChat:
                return FakeChat()

        monkeypatch.setitem(sys.modules, "openai", _fake_openai_module(FakeOpenAI))
        client = LLMClient(model="m", api_key="k")
        assert _deltas(client) == []

    def test_empty_stream_from_generator_completes(self) -> None:
        def gen(messages, model=None):
            return
            yield  # pragma: no cover

        client = LLMClient(call_func=gen)
        assert _deltas(client) == []