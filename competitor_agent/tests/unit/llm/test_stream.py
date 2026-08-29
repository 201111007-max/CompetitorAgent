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


def _consumed(client: LLMClient, messages: list[dict] | None = None) -> str:
    return "".join(
        d.text for d in client.stream(messages or [{"role": "user", "content": "hi"}])
        if d.kind == "text"
    )


class FakeDelta:
    def __init__(self, content="", reasoning="", tool_calls=None) -> None:
        self.content = content
        self.reasoning_content = reasoning
        self.tool_calls = tool_calls


class FakeFunc:
    def __init__(self, name=None, arguments="") -> None:
        self.name = name
        self.arguments = arguments


class FakeToolDelta:
    def __init__(self, index, id=None, function=None) -> None:
        self.index = index
        self.id = id
        self.function = function


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


class TestStreamMetering:
    """设计文档 63 §5.4：流式收尾记 ``llm.call`` 计价（成本核算与 complete() 一致）。"""

    def test_full_consumption_logs_llm_call(self, monkeypatch) -> None:
        def gen(messages, model=None):
            yield "你"
            yield "好"

        emitted = []

        def fake_emit(*args, **kwargs):
            emitted.append(kwargs)

        monkeypatch.setattr(
            "competitor_agent.llm.client.emit_session_event", fake_emit
        )
        long_msgs = [{"role": "system", "content": "你好世界你好世界你好"}]  # 9 字符 → 2 token
        client = LLMClient(call_func=gen)
        assert "".join(d.text for d in client.stream(long_msgs)) == "你好"
        assert client.total_cost_usd > 0, "流式完成后应累计成本"
        assert emitted, "流式完成后应发 llm.call 会话事件"
        assert emitted[0]["model"] == client._model
        assert emitted[0]["prompt_tokens"] > 0

    def test_empty_stream_does_not_log(self, monkeypatch) -> None:
        emitted = []

        def fake_emit(*args, **kwargs):
            emitted.append(kwargs)

        monkeypatch.setattr(
            "competitor_agent.llm.client.emit_session_event", fake_emit
        )

        def gen(messages, model=None):
            return
            yield  # pragma: no cover

        client = LLMClient(call_func=gen)
        assert "".join(d.text for d in client.stream([{"role": "user", "content": "hi"}])) == ""
        assert not emitted, "空流（无增量产出）不应记账"
        assert client.total_cost_usd == 0.0

    def test_early_break_still_logs_partial(self, monkeypatch) -> None:
        emitted = []

        def fake_emit(*args, **kwargs):
            emitted.append(kwargs)

        monkeypatch.setattr(
            "competitor_agent.llm.client.emit_session_event", fake_emit
        )

        def gen(messages, model=None):
            yield "思"
            yield "考"
            yield "中"

        client = LLMClient(call_func=gen)
        for d in client.stream([{"role": "user", "content": "hi"}]):
            break  # 消费首个增量即中断
        assert emitted, "提前中断也应记已产出部分"

    def test_sdk_usage_captured_for_metering(self, monkeypatch) -> None:
        class _U:
            pass

        u = _U()
        u.prompt_tokens = 10
        u.completion_tokens = 7

        created = {}

        class FakeCompletions:
            def create(self, *, model=None, messages=None, stream=False, **kw):
                created["stream"] = stream

                def it():
                    yield FakeChunk([FakeDelta(content="a")])
                    yield FakeChunk([FakeDelta(content="b")])
                    # 末 chunk 带 usage → 被 meter 捕获
                    yield FakeUsageChunk()

                return it()

        class FakeUsageChunk:
            def __init__(self) -> None:
                self.choices = [FakeChoice(FakeDelta())]
                self.usage = u

        class _Chat:
            @property
            def completions(self):
                return FakeCompletions()

        class FakeOpenAI:
            def __init__(self, **kwargs) -> None:
                pass

            @property
            def chat(self):
                return _Chat()

        monkeypatch.setitem(sys.modules, "openai", _fake_openai_module(FakeOpenAI))
        client = LLMClient(model="m", api_key="k")
        _consumed(client)
        assert created["stream"] is True


def _ToolChunk(chunk_dicts):
    class _R:
        pass

    r = _R()
    r.choices = []
    for c in chunk_dicts:
        m = c["message"]
        ch = _R()
        ch.message = _R()
        ch.message.content = m["content"]
        ch.message.tool_calls = m["tool_calls"]
        r.choices.append(ch)
    r.usage = None
    return r


class TestStreamToolCalling:
    """设计文档 63 M2：complete_with_tools 流式旁路——增量投递到 sink + 重构 ToolCallReply。"""

    def _fake_client(self, monkeypatch, chunks_iter, model="m", api_key="k", **kw) -> LLMClient:
        created = {}

        class FakeCompletions:
            def create(self, *, model=None, messages=None, stream=False, tools=None, **kk):
                created["stream"] = stream
                created["tools"] = tools
                return iter(chunks_iter)

        class _Chat:
            completions = FakeCompletions()

        class FakeOpenAI:
            def __init__(self, **kwargs) -> None:
                pass

            @property
            def chat(self) -> _Chat:
                return _Chat()

        monkeypatch.setitem(sys.modules, "openai", _fake_openai_module(FakeOpenAI))
        self._created = created
        return LLMClient(model=model, api_key=api_key, **kw)

    def test_streaming_reconstructs_tool_reply_and_emits_deltas(self, monkeypatch) -> None:
        chunk1 = FakeChunk([FakeDelta(reasoning="先做计划…")])
        chunk2 = FakeChunk([
            FakeDelta(tool_calls=[FakeToolDelta(index=0, id="call_abc", function=FakeFunc(name="make_plan", arguments='{"competitor":'))])
        ])
        chunk3 = FakeChunk([
            FakeDelta(tool_calls=[FakeToolDelta(index=0, function=FakeFunc(arguments='"cursor","resolution":"registry"}'))])
        ])
        client = self._fake_client(monkeypatch, [chunk1, chunk2, chunk3])

        sinks: list[StreamDelta] = []
        reply = client.complete_with_tools(
            [{"role": "user", "content": "hi"}],
            [{"type": "function", "function": {"name": "make_plan"}}],
            stream_sink=lambda d: sinks.append(d),
            message_id="lead_x",
        )
        # sink 收到 thinking 增量且归位 message_id
        assert [(d.kind, d.text, d.message_id) for d in sinks] == [
            ("thinking", "先做计划…", "lead_x"),
        ]
        # 重构出等价 ToolCallReply（工具名/id/参数 JSON 跨 chunk 拼接）
        assert reply.content == ""
        assert len(reply.tool_calls) == 1
        tc = reply.tool_calls[0]
        assert tc.id == "call_abc"
        assert tc.name == "make_plan"
        assert tc.arguments == {"competitor": "cursor", "resolution": "registry"}
        assert self._created["stream"] is True
        assert self._created["tools"] == [{"type": "function", "function": {"name": "make_plan"}}]

    def test_streaming_final_content_reply(self, monkeypatch) -> None:
        """设计文档 64 §3.2：Final-Answer（无 tool_calls）文本归 Payload 通道，不进正文。

        文本经 reply.content 回调用方（→ assemble → report 事件），而非递进 Stream 通道
        （sink）——报告 JSON 绝不进对话正文（与 doc 63 旧行为相反，即本设计的目标）。
        """
        client = self._fake_client(
            monkeypatch,
            [FakeChunk([FakeDelta(content="最终")]), FakeChunk([FakeDelta(content="结论")])],
        )
        sinks: list[StreamDelta] = []
        reply = client.complete_with_tools(
            [{"role": "user", "content": "hi"}], [], stream_sink=lambda d: sinks.append(d)
        )
        assert reply.content == "最终结论"
        assert reply.tool_calls == []
        # Final Answer 文本不再进 Stream 通道（sink 收到 0 条 text_delta）
        assert sinks == []

    def test_streaming_tool_round_text_still_sinked(self, monkeypatch) -> None:
        """设计文档 64 §3.2：叙述轮（有 tool_calls）的 text 仍递进 Stream 通道（正文打字机）。"""
        chunk1 = FakeChunk([FakeDelta(content="正在分析…")])
        chunk2 = FakeChunk([
            FakeDelta(tool_calls=[FakeToolDelta(index=0, id="call_1", function=FakeFunc(name="web_extract", arguments='{"url": "https://x.com"}'))])
        ])
        client = self._fake_client(monkeypatch, [chunk1, chunk2])
        sinks: list[StreamDelta] = []
        reply = client.complete_with_tools(
            [{"role": "user", "content": "hi"}],
            [{"type": "function", "function": {"name": "web_extract"}}],
            stream_sink=lambda d: sinks.append(d),
            turn=3,
        )
        # 叙述轮文本归正文，且携带 turn 段号
        assert [(d.kind, d.text, d.turn) for d in sinks] == [("text", "正在分析…", 3)]
        assert len(reply.tool_calls) == 1

    def test_streaming_final_content_chat_mode_still_sinked(self, monkeypatch) -> None:
        """设计文档 64 §5.2：对话式分支（final_as_payload=False）最终文本仍走 Stream 通道。"""
        client = self._fake_client(
            monkeypatch,
            [FakeChunk([FakeDelta(content="你好")]), FakeChunk([FakeDelta(content="，欢迎提问！")])],
        )
        sinks: list[StreamDelta] = []
        reply = client.complete_with_tools(
            [{"role": "user", "content": "hi"}],
            [],
            stream_sink=lambda d: sinks.append(d),
            turn=0,
            final_as_payload=False,
        )
        assert reply.content == "你好，欢迎提问！"
        # 对话答案经正文呈现（含 turn 段号）
        assert [(d.kind, d.text, d.turn) for d in sinks] == [
            ("text", "你好", 0),
            ("text", "，欢迎提问！", 0),
        ]

    def test_default_path_stays_non_streaming(self, monkeypatch) -> None:
        """无 stream_sink → 默认非流式（既有 54 调用方行为不变）。"""
        created = {}

        class FakeCompletions:
            def create(self, **kw):
                created.update(kw)
                return _ToolChunk([{"message": {"content": "ok", "tool_calls": []}}])

        class _Chat:
            completions = FakeCompletions()

        class FakeOpenAI:
            def __init__(self, **kwargs) -> None:
                pass

            @property
            def chat(self) -> _Chat:
                return _Chat()

        monkeypatch.setitem(sys.modules, "openai", _fake_openai_module(FakeOpenAI))
        client = LLMClient(model="m", api_key="k")
        reply = client.complete_with_tools([{"role": "user", "content": "hi"}], [{"type": "function", "function": {"name": "f"}}])
        assert reply.content == "ok"
        assert created.get("stream") is not True