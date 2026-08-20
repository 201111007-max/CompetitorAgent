"""设计文档 53 M1 — LLMClient.complete_with_tools 原生 tool-calling 通道

覆盖：
- 注入 call_func 双形态（Q3）：返回 ToolCallReply 原样采用、返回 str 包装为纯 content；
  tools/tool_choice kwargs 透传给 mock
- dict / SDK 对象形态响应的 tool_calls 抽取（id/name/arguments）
- arguments 非法 JSON → args_error 可读原因，不静默 {}（设计文档 38 语义）
- usage 计价累计（复用 _log_call 成本核算）
- Q4：端点不支持 tools（400 特征报错）→ LLMUnavailableError，指引含 protocol='react'；
  SDK 路径 tools/tool_choice 透传校验（monkeypatch openai.OpenAI，零网络）
- build_openai_tools：TOOL_SPECS 契约直映射；无 schema 工具从签名派生最小 parameters

全程 mock / fake client，不触真实网络与 API Key。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from competitor_agent.agent.tool_dispatcher import ToolDispatcher, ToolSpec
from competitor_agent.agent.tool_registry import build_openai_tools, build_react_dispatcher
from competitor_agent.config.loader import AppConfig
from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.llm.client import LLMClient, ToolCall, ToolCallReply


class FakeStatusError(Exception):
    """带 HTTP 状态码的伪 SDK 错误（模拟 openai APIStatusError.status_code）"""

    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(message or f"status {status_code}")
        self.status_code = status_code


MESSAGES = [{"role": "user", "content": "hi"}]
TOOLS_ARG = [{"type": "function", "function": {"name": "web_search", "parameters": {}}}]


class TestInjectedDoubleForm:
    """Q3 mock 双形态：收到 tools= kwarg 出 ToolCallReply，未收到出 str（此处两条路径都验）"""

    def test_reply_passthrough_and_kwargs_forwarded(self) -> None:
        seen: dict = {}
        reply = ToolCallReply(
            content="",
            tool_calls=[ToolCall(id="call_0", name="web_search", arguments={"query": "cursor"})],
        )

        def call_func(messages, model=None, tools=None, tool_choice=None):
            seen.update(tools=tools, tool_choice=tool_choice, model=model)
            return reply

        client = LLMClient(call_func=call_func, model="m0")
        out = client.complete_with_tools(MESSAGES, TOOLS_ARG, tool_choice="auto")
        assert out is reply
        assert seen["tools"] == TOOLS_ARG
        assert seen["tool_choice"] == "auto"
        assert seen["model"] == "m0"

    def test_str_wrapped_as_content_reply(self) -> None:
        client = LLMClient(call_func=lambda messages, model=None, **kw: "最终回答")
        out = client.complete_with_tools(MESSAGES, TOOLS_ARG)
        assert out.content == "最终回答"
        assert out.tool_calls == []


class TestExtractToolReply:
    def test_dict_shape(self) -> None:
        raw = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_abc",
                                "type": "function",
                                "function": {"name": "web_extract", "arguments": '{"url": "https://x"}'},
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        reply, usage = LLMClient._extract_tool_reply(raw)
        assert usage == {"prompt_tokens": 10, "completion_tokens": 5}
        assert reply.content == ""
        assert len(reply.tool_calls) == 1
        call = reply.tool_calls[0]
        assert call.id == "call_abc"
        assert call.name == "web_extract"
        assert call.arguments == {"url": "https://x"}
        assert call.args_error is None

    def test_sdk_object_shape(self) -> None:
        func = SimpleNamespace(name="github_stars", arguments='{"repo": "a/b"}')
        tc = SimpleNamespace(id="call_1", function=func)
        message = SimpleNamespace(content="done", tool_calls=[tc])
        raw = SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)
        reply, _usage = LLMClient._extract_tool_reply(raw)
        assert reply.content == "done"
        assert reply.tool_calls[0].name == "github_stars"
        assert reply.tool_calls[0].arguments == {"repo": "a/b"}

    def test_no_tool_calls_content_is_final(self) -> None:
        raw = {"choices": [{"message": {"content": "最终回答", "tool_calls": []}}]}
        reply, _ = LLMClient._extract_tool_reply(raw)
        assert reply.tool_calls == []
        assert reply.content == "最终回答"

    def test_invalid_arguments_json_args_error(self) -> None:
        """arguments 非法 JSON：不静默 {}，args_error 携带可读原因供回灌。"""
        raw = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {"id": "c1", "function": {"name": "web_search", "arguments": "{bad json"}}
                        ],
                    }
                }
            ]
        }
        reply, _ = LLMClient._extract_tool_reply(raw)
        call = reply.tool_calls[0]
        assert call.arguments == {}
        assert call.args_error is not None
        assert "不是合法 JSON" in call.args_error
        assert "{bad json" in call.args_error

    def test_non_object_arguments_args_error(self) -> None:
        raw = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [{"function": {"name": "web_search", "arguments": "[1, 2]"}}],
                    }
                }
            ]
        }
        reply, _ = LLMClient._extract_tool_reply(raw)
        call = reply.tool_calls[0]
        assert call.id == "call_0"  # 缺 id 时按序补 call_<idx>
        assert call.arguments == {}
        assert call.args_error is not None and "期望 JSON 对象" in call.args_error


class TestUsagePricing:
    def test_cost_accumulated(self) -> None:
        usage = SimpleNamespace(prompt_tokens=2000, completion_tokens=1000)
        reply = ToolCallReply(content="ok", usage=usage)
        client = LLMClient(call_func=lambda messages, model=None, **kw: reply)
        client.complete_with_tools(MESSAGES, TOOLS_ARG)
        # 2000/1000*0.0003 + 1000/1000*0.0006 = 0.0012
        assert client.total_cost_usd == pytest.approx(0.0012)

    def test_retry_then_success(self) -> None:
        """复用 _attempt_models：可重试错误退避后成功，native 通道可靠性语义不变。"""
        calls = {"n": 0}

        def call_func(messages, model=None, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise FakeStatusError(429)
            return ToolCallReply(content="ok")

        client = LLMClient(call_func=call_func, max_retries=3, backoff=0)
        out = client.complete_with_tools(MESSAGES, TOOLS_ARG)
        assert out.content == "ok"
        assert calls["n"] == 2


class _FakeCompletions:
    """伪 openai chat.completions：按预设抛错或返回，并记录 create kwargs（零网络）"""

    def __init__(self, *, exc: Exception | None = None, response: object = None) -> None:
        self._exc = exc
        self._response = response
        self.kwargs: dict = {}

    def create(self, **kwargs):
        self.kwargs.update(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._response


def _patch_openai(monkeypatch, completions: _FakeCompletions) -> None:
    class _FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            self.chat = SimpleNamespace(completions=completions)

    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)


class TestSdkPath:
    def test_tools_and_tool_choice_forwarded(self, monkeypatch) -> None:
        completions = _FakeCompletions(
            response={"choices": [{"message": {"content": "ok", "tool_calls": []}}]}
        )
        _patch_openai(monkeypatch, completions)
        client = LLMClient(model="m0", api_key="sk-fake")
        choice = {"type": "function", "function": {"name": "make_plan"}}
        out = client.complete_with_tools(MESSAGES, TOOLS_ARG, tool_choice=choice)
        assert completions.kwargs["tools"] == TOOLS_ARG
        assert completions.kwargs["tool_choice"] == choice
        assert out.content == "ok"

    def test_tool_choice_none_omitted(self, monkeypatch) -> None:
        completions = _FakeCompletions(
            response={"choices": [{"message": {"content": "ok"}}]}
        )
        _patch_openai(monkeypatch, completions)
        client = LLMClient(model="m0", api_key="sk-fake")
        client.complete_with_tools(MESSAGES, TOOLS_ARG)
        assert "tool_choice" not in completions.kwargs

    def test_tools_unsupported_raises_q4(self, monkeypatch) -> None:
        """Q4：400 + 工具特征报错 → LLMUnavailableError，含 protocol='react' 可操作指引。"""
        exc = FakeStatusError(400, "this model does not support tool_calls")
        _patch_openai(monkeypatch, _FakeCompletions(exc=exc))
        client = LLMClient(model="m0", api_key="sk-fake", fallback_models=["m1"])
        with pytest.raises(LLMUnavailableError, match=r"protocol='react'") as err:
            client.complete_with_tools(MESSAGES, TOOLS_ARG)
        assert "m0 不支持 tool_calls" in str(err.value)

    def test_tool_choice_rejected_raises_q4(self, monkeypatch) -> None:
        exc = FakeStatusError(400, "tool_choice is not supported by this endpoint")
        _patch_openai(monkeypatch, _FakeCompletions(exc=exc))
        client = LLMClient(model="m0", api_key="sk-fake")
        with pytest.raises(LLMUnavailableError, match=r"protocol='react'"):
            client.complete_with_tools(MESSAGES, TOOLS_ARG, tool_choice="auto")

    def test_plain_400_not_converted(self, monkeypatch) -> None:
        """与 tools 无关的 400（如上下文超长）保持原样抛出，不误判为 Q4。"""
        exc = FakeStatusError(400, "maximum context length exceeded")
        _patch_openai(monkeypatch, _FakeCompletions(exc=exc))
        client = LLMClient(model="m0", api_key="sk-fake")
        with pytest.raises(FakeStatusError):
            client.complete_with_tools(MESSAGES, TOOLS_ARG)


class TestBuildOpenaiTools:
    def test_mcp_specs_mapped(self) -> None:
        dispatcher = build_react_dispatcher(config=AppConfig())
        tools = build_openai_tools(dispatcher)
        assert len(tools) == dispatcher.tool_count
        by_name = {t["function"]["name"]: t for t in tools}
        assert set(by_name) == set(dispatcher.specs)
        for t in tools:
            assert t["type"] == "function"
        web_extract = by_name["web_extract"]["function"]
        assert web_extract["description"]
        params = web_extract["parameters"]
        assert params["properties"]["url"] == {"type": "string"}
        assert params["required"] == ["url"]
        assert "selector" in params["properties"]

    def test_exclude_respected(self) -> None:
        dispatcher = build_react_dispatcher(config=AppConfig(), exclude=("analyze_competitor",))
        names = {t["function"]["name"] for t in build_openai_tools(dispatcher)}
        assert "analyze_competitor" not in names

    def test_extra_tool_without_schema_derived_from_signature(self) -> None:
        def make_plan(goal: str, budget: float, note: str = "") -> str:
            return "ok"

        dispatcher = ToolDispatcher({"make_plan": make_plan})
        tools = build_openai_tools(dispatcher)
        func = tools[0]["function"]
        assert func["name"] == "make_plan"
        params = func["parameters"]
        assert params["type"] == "object"
        assert params["properties"] == {
            "goal": {"type": "string"},
            "budget": {"type": "number"},
            "note": {"type": "string"},
        }
        assert params["required"] == ["goal", "budget"]
        assert "description" not in func  # 无描述则不输出该键

    def test_registered_spec_without_schema_uses_spec_description(self) -> None:
        def noop() -> str:
            return "ok"

        dispatcher = ToolDispatcher()
        dispatcher.register("noop", noop, spec=ToolSpec(name="noop", func=noop, description="空操作"))
        func = build_openai_tools(dispatcher)[0]["function"]
        assert func["description"] == "空操作"
        assert func["parameters"] == {"type": "object", "properties": {}}
