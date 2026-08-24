"""设计文档 46 §3.2/§5：ReAct 上下文上限（Observation 截断 + 历史压缩 + task 只发首轮）

- task 只发首轮：消息累积进列表，不每轮重发完整 user_message（防上下文膨胀）
- 单条工具结果截断到 obs_max_chars（默认 4000），以 role:"tool" 消息回灌
- 工具步超过 max_history_steps 后折叠旧 turn 为规则摘要（保留 system + 任务 + 摘要块 + 最近 N 步）

设计文档 60：单协议（原生 function calling），tool 结果经 tool 角色消息回灌。
"""
import json

from competitor_agent.agent.react_agent import (
    _MAX_HISTORY_STEPS,
    _OBS_MAX_CHARS,
    _SUMMARY_MSG_PREFIX,
    ReactAgent,
)
from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.llm.client import LLMClient, ToolCall, ToolCallReply


def _tool(name: str, args: dict) -> ToolCallReply:
    return ToolCallReply(tool_calls=[ToolCall(id="call_0", name=name, arguments=args)])


class ScriptedLLM:
    """记录每次调用的 messages；前 n_actions 次返回工具调用，之后返回 Final Answer。"""

    def __init__(self, n_actions: int) -> None:
        self.calls: list[list[dict]] = []
        self._n = 0
        self._n_actions = n_actions

    def __call__(self, messages, model, **kwargs):
        self.calls.append([dict(m) for m in messages])
        self._n += 1
        if self._n <= self._n_actions:
            return _tool("echo", {"v": 1})
        return ToolCallReply(content="完成")

    @property
    def last_messages(self) -> list[dict]:
        return self.calls[-1]

    @staticmethod
    def user_contents(messages: list[dict]) -> list[str]:
        return [m["content"] for m in messages if m["role"] == "user"]

    @staticmethod
    def tool_contents(messages: list[dict]) -> list[str]:
        return [str(m.get("content", "")) for m in messages if m["role"] == "tool"]


def _agent(scripted: ScriptedLLM, tool_output: str = "ok") -> ReactAgent:
    return ReactAgent(
        llm=LLMClient(call_func=scripted),
        dispatcher=ToolDispatcher({"echo": lambda v: tool_output}),
    )


class TestTaskSentOnce:
    def test_task_only_first_round(self):
        """task 作为首条 user 消息，后续轮次不重发（每条 user 消息计数无重复 task）。"""
        scripted = ScriptedLLM(n_actions=2)
        agent = _agent(scripted)
        agent.run(agent.build_system_prompt(), "分析 Cursor 定价")
        for messages in scripted.calls:
            user = scripted.user_contents(messages)
            task_count = sum(1 for c in user if "分析 Cursor 定价" in c)
            assert task_count == 1, f"task 应只出现一次，实际 {task_count}"
        # 首条 user 消息必须是 task
        assert "分析 Cursor 定价" in scripted.calls[0][1]["content"]

    def test_tool_result_after_task(self):
        """工具结果以 tool 角色消息回灌（在 task 之后）。"""
        scripted = ScriptedLLM(n_actions=1)
        agent = _agent(scripted)
        agent.run(agent.build_system_prompt(), "任务")
        tools = scripted.tool_contents(scripted.last_messages)
        assert tools and "ok" in tools[0]
        assert scripted.last_messages[1]["content"] == "任务"


class TestObservationTruncation:
    def test_long_observation_truncated(self):
        """单条工具结果截断到 obs_max_chars，并带截断标记（原文不再完整出现）。"""
        long = "x" * 5000
        scripted = ScriptedLLM(n_actions=1)
        agent = _agent(scripted, tool_output=long)
        agent.run(agent.build_system_prompt(), "任务", obs_max_chars=100)
        tools = scripted.tool_contents(scripted.last_messages)
        obs = tools[0]
        assert "（内容过长已截断）" in obs
        assert long not in obs  # 完整原文被截断，不再入上下文

    def test_short_observation_not_truncated(self):
        scripted = ScriptedLLM(n_actions=1)
        agent = _agent(scripted, tool_output="short")
        agent.run(agent.build_system_prompt(), "任务", obs_max_chars=100)
        tools = scripted.tool_contents(scripted.last_messages)
        assert "short" in tools[0]
        assert "截断" not in tools[0]


class TestHistoryCompression:
    def test_history_bounded_after_many_steps(self):
        """工具步超过 max_history_steps 后消息数被压缩到有界（含摘要块）。"""
        scripted = ScriptedLLM(n_actions=10)
        agent = _agent(scripted)
        agent.run(
            agent.build_system_prompt(),
            "任务",
            max_steps=12,
            max_history_steps=2,
        )
        # system + task + 摘要块 + 最近 2*max_history_steps 个 turn（每 turn = assistant + tool）
        assert len(scripted.last_messages) <= 2 + 1 + 2 * 2 * 2
        # 压缩后仍保留首条任务（消息位置 1）
        assert scripted.last_messages[1]["content"] == "任务"
        # 折叠为摘要而非整体丢弃：摘要块存在于上下文中，且携带旧步信息
        users = scripted.user_contents(scripted.last_messages)
        summary = next((c for c in users if c.startswith(_SUMMARY_MSG_PREFIX)), "")
        assert summary, "压缩后应存在旧步摘要块"
        assert "调用 echo" in summary
        # 最新工具结果仍保留（最后一条 tool 消息）
        tools = scripted.tool_contents(scripted.last_messages)
        assert tools and "ok" in tools[-1]

    def test_no_compression_under_limit(self):
        scripted = ScriptedLLM(n_actions=1)
        agent = _agent(scripted)
        agent.run(agent.build_system_prompt(), "任务", max_history_steps=8)
        # 1 步 = system + task + assistant + tool = 4 条，未达压缩线
        assert len(scripted.last_messages) == 4

    def test_default_constants(self):
        assert _OBS_MAX_CHARS == 4000
        assert _MAX_HISTORY_STEPS == 8

    def test_compress_history_folds_old_turns_into_summary(self):
        """_compress_history 直接单测（native turn 形状）：保留 system + task + 摘要块 + 最近 2*N 个 turn。"""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "任务"},
        ]
        for i in range(6):
            messages.append({
                "role": "assistant",
                "tool_calls": [{
                    "id": f"c{i}", "type": "function",
                    "function": {"name": "echo", "arguments": json.dumps({"v": i})},
                }],
            })
            messages.append({
                "role": "tool", "tool_call_id": f"c{i}",
                "content": f"<untrusted_data>\nres{i}\n</untrusted_data>",
            })
        out, summary = ReactAgent._compress_history(messages, max_history_steps=2)
        # system + task + 摘要块 + 最近 2*2 个 turn（每 turn = assistant + tool）
        assert len(out) == 2 + 1 + 4 * 2
        assert out[0] == {"role": "system", "content": "sys"}
        assert out[1] == {"role": "user", "content": "任务"}
        # 保留最近 2*2 个 turn（res2-res5），被折叠的旧步（res0/res1）不再以全文出现
        assert "res5" in out[-1]["content"]
        assert "res2" in out[4]["content"]
        joined = "".join(str(m.get("content", "")) for m in out)
        assert "<untrusted_data>\nres0\n" not in joined and "<untrusted_data>\nres1\n" not in joined
        # 旧步折叠为摘要而非丢弃：工具名 + 结果前 N 字可回溯（被折叠四对都在）
        assert summary
        assert "调用 echo → res0" in summary
        assert "调用 echo → res1" in summary

    def test_fold_native_turn_extracts_tool_and_url(self):
        """折叠行（native）：工具步提取工具名 + URL + 结果前 N 字（确定性，无 LLM）。"""
        turn = [
            {
                "role": "assistant",
                "tool_calls": [{
                    "id": "c0", "type": "function",
                    "function": {
                        "name": "web_extract",
                        "arguments": json.dumps({"url": "https://example.com/a"}),
                    },
                }],
            },
            {"role": "tool", "tool_call_id": "c0",
             "content": "<untrusted_data>\nPro $20/month\n</untrusted_data>"},
        ]
        line = ReactAgent._fold_native_turn(turn)
        assert line == "调用 web_extract [https://example.com/a] → Pro $20/month"
