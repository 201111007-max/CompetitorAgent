"""agent 层单测：tool_dispatcher / react_agent / react_loop

设计文档 60：单协议（原生 function calling），mock 以 ToolCallReply 形状回放
脚本（动作步 = ToolCall，收尾 = 纯 content）。
"""
from __future__ import annotations

import time
from typing import Any, ClassVar

import pytest
from competitor_agent.agent import (
    ReactAgent,
    ReactLoop,
    ToolArgumentError,
    ToolDispatcher,
    ToolSpec,
)
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.llm.client import LLMClient, ToolCall, ToolCallReply


def _tool(name: str, args: dict[str, Any]) -> ToolCallReply:
    return ToolCallReply(tool_calls=[ToolCall(id="call_0", name=name, arguments=args)])


def _fin(text: str) -> ToolCallReply:
    return ToolCallReply(content=text)


def _scripted(responses: list[ToolCallReply], track: list | None = None):
    """构造接受 ``**kwargs``（tools/tool_choice）的顺序回放 call_func（native 单协议）。"""
    calls = {"n": 0}

    def fake_llm(messages, model, **kwargs):
        if track is not None:
            track.append(list(messages))
        r = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return r

    return fake_llm


class TestToolDispatcher:
    def test_register_and_dispatch(self):
        d = ToolDispatcher()
        d.register("add", lambda a, b: a + b)
        assert d.dispatch("add", {"a": 1, "b": 2}) == "3"

    def test_unknown_tool_raises(self):
        d = ToolDispatcher()
        try:
            d.dispatch("nope", {})
            assert False, "应抛 ValueError"
        except ValueError:
            pass

    def test_validate_tool(self):
        d = ToolDispatcher()
        d.register("x", lambda: "ok")
        assert d.validate_tool("x")
        assert not d.validate_tool("y")

    def test_descriptions(self):
        d = ToolDispatcher()
        d.register("web_extract", lambda url: "")
        desc = d.get_tool_descriptions()
        assert "web_extract" in desc

    def test_tool_count(self):
        d = ToolDispatcher({"a": lambda: "", "b": lambda: ""})
        assert d.tool_count == 2


class TestReactAgent:
    def _make_agent(self, responses, tools=None):
        return ReactAgent(
            llm=LLMClient(call_func=_scripted(responses)),
            dispatcher=tools or ToolDispatcher({"web_extract": lambda url: "fetched"}),
        )

    def test_run_reaches_final_answer(self):
        agent = self._make_agent([
            _tool("web_extract", {"url": "https://x.com"}),
            _fin("页面已抓取"),
        ])
        answer = agent.run(agent.build_system_prompt(), "分析定价")
        assert answer == "页面已抓取"

    def test_run_handles_unknown_tool(self):
        agent = self._make_agent([
            _tool("ghost_tool", {}),
            _fin("完成"),
        ])
        answer = agent.run(agent.build_system_prompt(), "任务")
        assert answer == "完成"

    def test_run_max_steps_returns_warning(self):
        agent = self._make_agent([_tool("web_extract", {"url": "https://x.com"})] * 7)
        answer = agent.run(agent.build_system_prompt(), "任务", max_steps=3)
        assert "最大推理步数" in answer

    def test_system_prompt_native_no_tool_descriptions(self):
        """设计文档 60：native 系统提示不含工具文本描述（工具经 tools 请求参数下发）。"""
        agent = self._make_agent([_fin("x")])
        prompt = agent.build_system_prompt()
        assert "web_extract" not in prompt
        assert "你是竞品情报分析 Agent" in prompt

    def test_build_system_prompt_with_instructions(self):
        agent = self._make_agent([_fin("x")])
        prompt = agent.build_system_prompt(instructions="专项指令")
        assert "专项指令" in prompt


class TestReactLoop:
    def test_emits_events_and_returns_answer(self):
        events = []

        def sink(e: ProgressEvent):
            events.append(e)

        agent = ReactAgent(
            llm=LLMClient(call_func=_scripted([_fin("结论")])),
            dispatcher=ToolDispatcher(),
        )
        loop = ReactLoop(agent, event_sink=sink)
        answer = loop.run("分析 cursor")
        assert answer == "结论"
        assert any(e.event == "phase_start" for e in events)
        assert any(e.event == "phase_complete" for e in events)


class TestToolSchema:
    """设计文档 38：params_schema 校验 → ToolArgumentError 可读回灌"""

    SCHEMA: ClassVar[dict[str, object]] = {
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {"type": "string"},
            "mode": {"type": "string", "enum": ["a", "b"]},
        },
    }

    def _make(self):
        d = ToolDispatcher()
        d.register(
            "web_extract",
            lambda url, mode="a": f"fetched:{url}",
            spec=ToolSpec(
                "web_extract",
                lambda url, mode="a": "x",
                params_schema=self.SCHEMA,
            ),
        )
        return d

    def test_valid_args_pass(self):
        assert self._make().dispatch("web_extract", {"url": "https://x.com"}) == "fetched:https://x.com"

    def test_missing_required_raises(self):
        with pytest.raises(ToolArgumentError, match="缺少必填字段 url"):
            self._make().dispatch("web_extract", {})

    def test_wrong_type_raises(self):
        with pytest.raises(ToolArgumentError, match="期望 string"):
            self._make().dispatch("web_extract", {"url": 123})

    def test_enum_out_of_range_raises(self):
        with pytest.raises(ToolArgumentError, match="枚举"):
            self._make().dispatch("web_extract", {"url": "x", "mode": "c"})

    def test_descriptions_include_param_types(self):
        desc = self._make().get_tool_descriptions()
        assert "web_extract(url:string" in desc or "web_extract(url: string" in desc
        assert "mode?:string" in desc


class TestToolTimeout:
    """设计文档 38：超时返回可读文本，不悬挂循环"""

    def test_timeout_returns_readable(self):
        def slow(secs):
            time.sleep(secs)

        d = ToolDispatcher()
        d.register("slow", slow, spec=ToolSpec("slow", slow, timeout=0.05))
        assert d.dispatch("slow", {"secs": 5}) == "工具执行超时: slow"

    def test_no_timeout_runs_normally(self):
        d = ToolDispatcher()
        d.register("add", lambda a, b: a + b)
        assert d.dispatch("add", {"a": 1, "b": 2}) == "3"


class TestNativeFeedback:
    """设计文档 38：四类反馈（解析失败/参数错误/工具不存在/执行异常）回灌 tool 消息"""

    def _run(self, responses, tools):
        seen = []

        def fake_llm(messages, model, **kwargs):
            seen.append([dict(m) for m in messages])
            return responses[min(len(seen) - 1, len(responses) - 1)]

        agent = ReactAgent(llm=LLMClient(call_func=fake_llm), dispatcher=tools)
        return agent.run(agent.build_system_prompt(), "任务"), seen

    @staticmethod
    def _observations(seen):
        # 回灌文本在 tool 角色消息（native 单协议，设计文档 60）
        return [str(m.get("content", "")) for msgs in seen for m in msgs if m["role"] == "tool"]

    def test_argument_error_feedback(self):
        d = ToolDispatcher()
        d.register(
            "web_extract",
            lambda url: "ok",
            spec=ToolSpec(
                "web_extract",
                lambda url: "ok",
                params_schema={"type": "object", "required": ["url"],
                               "properties": {"url": {"type": "string"}}},
            ),
        )
        _, seen = self._run(
            [_tool("web_extract", {"url": 123}), _fin("完成")],
            d,
        )
        assert any("工具参数错误" in m for m in self._observations(seen))

    def test_unknown_tool_feedback(self):
        _, seen = self._run(
            [_tool("ghost", {}), _fin("完成")],
            ToolDispatcher(),
        )
        assert any("工具不可用" in m for m in self._observations(seen))

    def test_execution_exception_feedback(self):
        def boom(**kwargs):
            raise RuntimeError("内部故障")

        d = ToolDispatcher({"boom": boom})
        _, seen = self._run(
            [_tool("boom", {}), _fin("完成")],
            d,
        )
        assert any("工具执行异常" in m for m in self._observations(seen))
        assert any("内部故障" in m for m in self._observations(seen))

    def test_args_parse_error_feedback(self):
        """arguments 非法 JSON → args_error → 可读回灌（设计文档 38/53 语义）。"""
        bad_call = ToolCallReply(
            tool_calls=[ToolCall(id="call_0", name="web_extract", arguments={},
                                 args_error="arguments 不是合法 JSON: 测试")],
        )
        _, seen = self._run([bad_call, _fin("完成")], ToolDispatcher())
        assert any("工具参数解析失败" in m for m in self._observations(seen))


class TestNativeRecovery:
    """设计文档 38 集成：参数错误→回灌→修正参数→工具成功调用（自恢复闭环）"""

    def test_recovers_from_bad_args_to_valid(self):
        calls = []

        def web_extract(url):
            calls.append(url)
            return f"fetched:{url}"

        d = ToolDispatcher()
        d.register(
            "web_extract",
            web_extract,
            spec=ToolSpec(
                "web_extract",
                web_extract,
                params_schema={"type": "object", "required": ["url"],
                               "properties": {"url": {"type": "string"}}},
            ),
        )

        responses = [
            _tool("web_extract", {"url": 123}),
            _tool("web_extract", {"url": "https://x.com"}),
            _fin("完成"),
        ]
        agent = ReactAgent(llm=LLMClient(call_func=_scripted(responses)), dispatcher=d)
        answer = agent.run(agent.build_system_prompt(), "任务")
        assert answer == "完成"
        assert calls == ["https://x.com"]
