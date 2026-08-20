"""设计文档 53 M2 — 原生 Function Calling 协议（native 循环）

覆盖：
- native 循环端到端（双形态 mock：收到 tools= 出 ToolCallReply）
- tool_choice plan-first 首轮强制（API 层保证首步 make_plan，零浪费步数）
- tool 角色消息回灌含 tool_call_id（role:"tool" + tool_call_id 对应）
- 并行 tool_calls 按序逐个执行、逐条回灌
- 历史压缩适配（assistant(tool_calls)+tool 对折叠，不丢任务）
- arguments 非法 JSON → 回灌自恢复（设计文档 38 语义，不静默 {}）
- system prompt native 模式不含工具文本描述与格式说明句

全程 mock、零真实网络与 API Key。
"""
from __future__ import annotations

import json

import pytest
from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.agent.react_loop import ReactLoop
from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.llm.client import LLMClient, ToolCall, ToolCallReply

from competitor_agent.agent.tool_registry import build_openai_tools


def _reply(content: str = "", *calls: ToolCall) -> ToolCallReply:
    return ToolCallReply(content=content, tool_calls=list(calls))


class ScriptedLLM:
    """脚本化双形态 mock：按 staged 依次出 ToolCallReply（缺省回 Final Answer）。"""

    def __init__(self, stages: list[ToolCallReply]) -> None:
        self.stages = list(stages)
        self.i = 0
        self.tools_seen: list = []
        self.tool_choices: list = []

    def __call__(self, messages, model=None, **kwargs):
        self.tools_seen.append(kwargs.get("tools"))
        self.tool_choices.append(kwargs.get("tool_choice"))
        reply = self.stages[min(self.i, len(self.stages) - 1)]
        self.i += 1
        return reply

    def __len__(self) -> int:
        return max(0, len(self.stages) - self.i)


def _single_call(name: str, args: dict, call_id: str = "call_0") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=args)


def _make_agent(llm: LLMClient) -> ReactAgent:
    d = ToolDispatcher(
        {
            "make_plan": lambda plan_json: json.dumps(plan_json, ensure_ascii=False) if isinstance(plan_json, dict) else "E",
            "echo": lambda v: f"echo:{v}",
            "web_search": lambda query, url="": f"search:{query}",
        }
    )
    return ReactAgent(llm=llm, dispatcher=d)


def _final(text: str) -> ToolCallReply:
    return _reply(content=text)


class TestNativeLoopEndToEnd:
    def test_full_tool_loop_returns_content(self):
        """native 端到端：make_plan → web_search → content(Final Answer)。"""
        scripted = ScriptedLLM([
            _reply("", _single_call("make_plan", {"plan_json": {"competitor": "c", "dimensions": ["pricing"]}})),
            _reply("", _single_call("web_search", {"query": "cursor"}, "call_1")),
            _final('{"competitor": "c", "dimensions": []}'),
        ])
        agent = _make_agent(LLMClient(call_func=scripted))
        answer = agent.run(agent.build_system_prompt(), "分析 cursor")
        assert answer == '{"competitor": "c", "dimensions": []}'
        # tools 参数下发、tool_choice 首轮后解除（Non plan 段为 None）
        assert scripted.tools_seen[0] is not None

    def test_tools_request_not_text_controller(self):
        """tools 参数下发基于契约（build_openai_tools），而非文本描述。"""
        scripted = ScriptedLLM([_final("ok")])
        agent = _make_agent(LLMClient(call_func=scripted))
        agent.run(agent.build_system_prompt(), "任务")
        tools = scripted.tools_seen[0] or []
        names = {t["function"]["name"] for t in tools}
        assert "make_plan" in names and "echo" in names and "web_search" in names


class TestPlanFirstToolChoice:
    def test_first_round_forces_make_plan(self):
        """plan-first：首轮 tool_choice 强制 make_plan，命中后解除。"""
        scripted = ScriptedLLM([
            _reply("", _single_call("make_plan", {"plan_json": {"competitor": "c", "dimensions": []}})),
            _final("done"),
        ])
        agent = _make_agent(LLMClient(call_func=scripted))
        loop = ReactLoop(agent, plan_first=True)
        loop.run("分析 cursor")
        assert scripted.tool_choices[0] == {"type": "function", "function": {"name": "make_plan"}}
        # 首轮命中后，后续轮 tool_choice 解除（None = 让模型自由选）
        assert scripted.tool_choices[1] is None
        assert loop.plan == {"competitor": "c", "dimensions": []}

    def test_outside_plan_first_auto_choice(self):
        """无 plan_first：tool_choice 恒 None（原生协议不强加约束）。"""
        scripted = ScriptedLLM([_reply("", _single_call("web_search", {"query": "x"})), _final("f")])
        agent = _make_agent(LLMClient(call_func=scripted))
        agent.run(agent.build_system_prompt(), "任务")
        assert scripted.tool_choices[0] is None


class TestToolRoleMessages:
    def test_tool_result_carries_tool_call_id(self):
        """tool 角色消息带 tool_call_id，供 SDK 关联 tool_call。"""
        captured: list[dict] = []

        def spy(messages, model=None, **kwargs):
            captured.append([dict(m) for m in messages])
            if len(captured) == 1:
                return _reply("", _single_call("echo", {"v": 1}, "tc_echo"))
            return _final("done")

        agent = _make_agent(LLMClient(call_func=spy))
        agent.run(agent.build_system_prompt(), "任务")
        sent = captured[1]
        tool_msgs = [m for m in sent if m["role"] == "tool"]
        assert tool_msgs, "native 循环应回灌 tool 角色消息"
        assert tool_msgs[0]["tool_call_id"] == "tc_echo"
        if "echo:1" not in tool_msgs[0]["content"]:
            assert "<untrusted_data" in tool_msgs[0]["content"]  # 包裹不可信块
        # assistant 消息携带 tool_calls（SDK 兼容花形）
        assistant_msgs = [m for m in sent if m["role"] == "assistant" and m.get("tool_calls")]
        assert assistant_msgs and assistant_msgs[0]["tool_calls"][0]["id"] == "tc_echo"

    def test_parallel_calls_dispatched_in_order(self):
        """并行 tool_calls：一期按序逐个执行、逐条回灌 tool 消息。"""
        order: list[str] = []
        captured: list[dict] = []

        def spy(messages, model=None, **kwargs):
            captured.append([dict(m) for m in messages])
            if len(captured) == 1:
                return _reply(
                    "",
                    _single_call("echo", {"v": 1}, "c1"),
                    _single_call("echo", {"v": 2}, "c2"),
                    _single_call("echo", {"v": 3}, "c3"),
                )
            return _final("done")

        d = ToolDispatcher({"echo": lambda v: (order.append(f"e{v}"), f"echo:{v}")[1]})
        agent = ReactAgent(llm=LLMClient(call_func=spy), dispatcher=d)
        answer = agent.run(agent.build_system_prompt(), "任务")
        assert answer == "done"
        assert order == ["e1", "e2", "e3"]  # 按 tool_call 顺序逐个执行
        sent = captured[1]
        tool_msgs = [m for m in sent if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in tool_msgs] == ["c1", "c2", "c3"]  # 逐条回灌


class TestNativeHistoryCompression:
    def test_task_preserved_after_compression(self):
        """压缩适配不丢任务：折叠大量旧工具步后 task 仍在首条 user。"""
        stages = [_reply("", _single_call("echo", {"v": i}, f"c{i}")) for i in range(20)]
        stages.append(_final("done"))
        captured: list[dict] = []

        def spy(messages, model=None, **kwargs):
            captured.append([dict(m) for m in messages])
            return stages[min(len(captured) - 1, len(stages) - 1)]

        agent = _make_agent(LLMClient(call_func=spy))
        answer = _run_long(agent, "分析 cursor 定价就要看官网")
        assert answer == "done"
        last = captured[-1]
        first_user = next(m["content"] for m in last if m["role"] == "user")
        assert "分析 cursor 定价就要看官网" in first_user  # 任务未被折叠丢弃

    def test_compressed_turn_still_summarized(self):
        """压缩折叠产物为工具名/结果前 N 字摘要（无 LLM 规则）。"""
        captured: list[dict] = []

        def spy(messages, model=None, **kwargs):
            captured.append([dict(m) for m in messages])
            if len(captured) <= 20:
                return _reply("", _single_call("echo", {"v": 1}, "cx"))
            return _final("done")

        agent = _make_agent(LLMClient(call_func=spy))
        answer = _run_long(agent, "任务")
        assert answer == "done"
        last = captured[-1]
        summaries = [str(m.get("content", "")) for m in last if str(m.get("content", "")).startswith("已压缩的旧工具步摘要")]
        assert summaries, "native 历史压缩应产出摘要块"
        assert "echo" in summaries[0] or "echo:1" in summaries[0]


def _run_long(agent: ReactAgent, task: str) -> str:
    """native 密步场景跑到收尾（步数上限放宽，压缩归终结）。"""
    return agent.run(agent.build_system_prompt(), task, max_steps=40)


class TestArgsErrorSelfHeal:
    def test_invalid_arguments_fed_back_then_corrected(self):
        """arguments 非法 JSON → 可读 args_error 回灌 → 模型修正自恢复。"""
        calls: dict = {"n": 0, "msgs": []}

        def llm_mock(messages, model=None, **kwargs):
            calls["n"] += 1
            calls["msgs"].append([dict(m) for m in messages])
            if calls["n"] == 1:
                return _reply(
                    "",
                    ToolCall(id="cbad", name="web_search", arguments={}, args_error="arguments 不是合法 JSON: {bad"),
                )
            if calls["n"] == 2:
                return _reply("", _single_call("web_search", {"query": "cursor"}, "cok"))
            return _final("自恢复成功")

        agent = _make_agent(LLMClient(call_func=llm_mock))
        answer = agent.run(agent.build_system_prompt(), "任务", max_steps=10)
        assert "自恢复成功" in answer
        # 第二轮应收到首轮非法参数的 tool 角色回灌（可读 args_error）
        tool_msgs = [m for m in calls["msgs"][1] if m.get("role") == "tool"]
        assert any("<untrusted_data" in str(m.get("content", "")) for m in tool_msgs)

    def test_dispatch_call_args_error_branch(self):
        """_dispatch_call 对 args_error 返回可读回灌，不静默 {}。"""
        agent = _make_agent(LLMClient())
        call = ToolCall(id="x", name="web_search", arguments={}, args_error="坏参数")
        out = agent._dispatch_call(call)
        assert out.startswith("工具参数解析失败")
        assert "坏参数" in out


def test_native_system_prompt_drops_text_format_help():
    """native 模式：系统提示不含工具文本描述与 Thought/Action 格式说明（省 token）。"""
    d = ToolDispatcher({"web_search": lambda query: "r"})
    agent = ReactAgent(llm=LLMClient(), dispatcher=d, protocol="native")
    prompt = agent.build_system_prompt()
    assert "Thought/Action/Final Answer" not in prompt
    assert "可用工具" not in prompt
    assert "web_extract" not in prompt  # 工具经 tools 参数下发，不再文本描述
    agent.protocol = "react"
    prompt_r = agent.build_system_prompt()
    assert "Thought/Action/Final Answer" in prompt_r
    assert "web_search" in prompt_r  # 工具文本描述在 react 模式保留


def test_invalid_protocol_rejected():
    with pytest.raises(ValueError):
        ReactAgent(llm=LLMClient(), dispatcher=ToolDispatcher(), protocol="bogus")
    agent = ReactAgent(llm=LLMClient(), dispatcher=ToolDispatcher())
    with pytest.raises(ValueError):
        agent.protocol = "bogus"


def test_build_system_respects_protocol_switch():
    agent = ReactAgent(llm=LLMClient(), dispatcher=ToolDispatcher({"web_search": lambda query: "r"}))
    assert agent.protocol == "native"  # 默认 native（设计文档 53 Q1）
    assert "Thought/Action/Final Answer" not in agent.build_system_prompt()
    agent.protocol = "react"
    assert "Thought/Action/Final Answer" in agent.build_system_prompt()
    assert agent.protocol == "react"