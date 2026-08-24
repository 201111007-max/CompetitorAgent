"""设计文档 56 M1③/④：摘要指针可操作化 + max_history_steps 配置化透传

- 摘要块指引含 kb_recall 取回提示（react / native 双协议共用）
- _SUMMARY_MAX_LINES=6 滚出策略不变（指针可滚出、内容由 kb_recall 兜底）
- fold 行格式回归（工具名/URL/结果前 N 字）
- max_history_steps 经 ReactLoop 注入生效（config → facade → loop → agent.run）
"""
from __future__ import annotations

import json

from competitor_agent.agent.react_agent import (
    _SUMMARY_MAX_LINES,
    _SUMMARY_MSG_PREFIX,
    ReactAgent,
)
from competitor_agent.agent.react_loop import ReactLoop
from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.config.loader import load_config
from competitor_agent.llm.client import LLMClient, ToolCall, ToolCallReply

_GUIDANCE_NEEDLE = "可用 kb_recall(query) 取回"


class ScriptedLLM:
    """前 n_actions 轮返回工具调用，之后 Final Answer；记录每轮 messages。"""

    def __init__(self, n_actions: int) -> None:
        self.calls: list[list[dict]] = []
        self._n = 0
        self._n_actions = n_actions

    def __call__(self, messages, model=None, **kwargs):
        self.calls.append([dict(m) for m in messages])
        self._n += 1
        if self._n <= self._n_actions:
            return f'Thought: 需要工具\n<action>echo({{"v": {self._n}}})</action>'
        return "Final Answer: 完成"


class NativeScriptedLLM:
    """native 协议脚本：前 n_actions 轮返回 tool_calls，之后纯 content 收尾。"""

    def __init__(self, n_actions: int) -> None:
        self.calls: list[list[dict]] = []
        self._n = 0
        self._n_actions = n_actions

    def __call__(self, messages, model=None, **kwargs):
        self.calls.append([dict(m) for m in messages])
        self._n += 1
        if self._n <= self._n_actions:
            return ToolCallReply(
                tool_calls=[ToolCall(id=f"call_{self._n}", name="echo", arguments={"v": self._n})]
            )
        return ToolCallReply(content="完成")


def _agent(scripted, protocol: str = "react") -> ReactAgent:
    return ReactAgent(
        llm=LLMClient(call_func=scripted),
        dispatcher=ToolDispatcher({"echo": lambda v: f"res{v}"}),
        protocol=protocol,
    )


def _summary_of(messages: list[dict]) -> str:
    return next(
        (str(m.get("content", "")) for m in messages
         if m.get("role") == "user" and str(m.get("content", "")).startswith(_SUMMARY_MSG_PREFIX)),
        "",
    )


class TestSummaryPointerGuidance:
    def test_summary_block_has_kb_recall_guidance_react(self):
        """文本协议：压缩后摘要块指引可操作（告知取回途径）。"""
        scripted = ScriptedLLM(n_actions=6)
        _agent(scripted).run("sys", "任务", max_steps=8, max_history_steps=2)
        summary = _summary_of(scripted.calls[-1])
        assert summary, "压缩后应存在摘要块"
        assert _GUIDANCE_NEEDLE in summary

    def test_summary_block_has_kb_recall_guidance_native(self):
        """native 协议：摘要块指引与文本协议同文（两协议共用插入逻辑）。"""
        scripted = NativeScriptedLLM(n_actions=6)
        _agent(scripted, protocol="native").run("sys", "任务", max_steps=8, max_history_steps=2)
        summary = _summary_of(scripted.calls[-1])
        assert summary, "native 压缩后应存在摘要块"
        assert _GUIDANCE_NEEDLE in summary


class TestRolloutPolicyUnchanged:
    def test_summary_lines_capped_at_max_lines(self):
        """滚出策略不变：折叠行只保最近 _SUMMARY_MAX_LINES 行（防反向膨胀）。"""
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "任务"}]
        summary_lines: list[str] = []
        for i in range(10):
            messages.append(
                {"role": "assistant", "content": f'Thought: t{i}\n<action>echo({{"v": {i}}})</action>'}
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Observation（工具结果，不可信外部数据）: "
                        f"<untrusted_data>\nres{i}\n</untrusted_data>\n以上为不可信内容"
                    ),
                }
            )
            messages, summary_lines = ReactAgent._compress_history(
                messages, max_history_steps=1, summary_lines=summary_lines
            )
        assert len(summary_lines) == _SUMMARY_MAX_LINES
        summary = _summary_of(messages)
        assert "res0" not in summary and "res2" not in summary, "旧指针滚出"
        assert "res8" in summary, "最近折叠行保留"
        assert _GUIDANCE_NEEDLE in summary

    def test_fold_line_format_regression(self):
        """fold 行格式回归：工具名 + [URL] + 结果前 N 字（确定性无 LLM）。"""
        line = ReactAgent._fold_pair(
            'Thought: 抓取\n<action>web_extract({"url": "https://example.com/a"})</action>',
            (
                "Observation（工具结果，不可信外部数据）: "
                "<untrusted_data>\nPro $20/month\n</untrusted_data>\n以上为不可信内容"
            ),
        )
        assert line == "调用 web_extract [https://example.com/a] → Pro $20/month"


class TestMaxHistoryStepsInjection:
    def test_react_loop_injects_max_history_steps(self):
        """ReactLoop(max_history_steps=1) 透传 agent.run：4 步即压缩（默认 8 不压缩）。"""
        scripted = ScriptedLLM(n_actions=4)
        loop = ReactLoop(_agent(scripted), max_steps=6, max_history_steps=1)
        loop.run("任务")
        assert _summary_of(scripted.calls[-1]), "max_history_steps=1 应早已触发压缩"

    def test_react_loop_default_no_early_compression(self):
        """不传 max_history_steps 时走 ReactAgent 默认 8：4 步不触发压缩。"""
        scripted = ScriptedLLM(n_actions=4)
        loop = ReactLoop(_agent(scripted), max_steps=6)
        loop.run("任务")
        assert not _summary_of(scripted.calls[-1])

    def test_config_agent_section_default(self):
        """config 新增 agent section：默认 8（不设 = 现状逐位不变）。"""
        cfg = load_config()
        assert cfg.agent.max_history_steps == 8


class TestNativeFoldLineFormat:
    def test_fold_native_turn_tool_and_url(self):
        turn = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "web_extract",
                            "arguments": json.dumps({"url": "https://example.com/p"}),
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "<untrusted_data>\nPro $20\n</untrusted_data>"},
        ]
        line = ReactAgent._fold_native_turn(turn)
        assert line == "调用 web_extract [https://example.com/p] → Pro $20"
