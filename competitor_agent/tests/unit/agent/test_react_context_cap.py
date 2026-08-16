"""设计文档 46 §3.2/§5：ReAct 上下文上限（Observation 截断 + 历史压缩 + task 只发首轮）

- task 只发首轮：消息累积进列表，不每轮重发完整 user_message（防上下文膨胀）
- 单条 Observation 截断到 obs_max_chars（默认 4000）
- 工具步超过 max_history_steps 后压缩旧步（保留 system + 任务 + 最近 N 步）
"""
from competitor_agent.agent.react_agent import (
    _MAX_HISTORY_STEPS,
    _OBS_MAX_CHARS,
    ReactAgent,
)
from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.llm.client import LLMClient


class ScriptedLLM:
    """记录每次调用的 messages；前 n_actions 次返回工具调用，之后返回 Final Answer。"""

    def __init__(self, n_actions: int) -> None:
        self.calls: list[list[dict]] = []
        self._n = 0
        self._n_actions = n_actions

    def __call__(self, messages, model):
        self.calls.append([dict(m) for m in messages])
        self._n += 1
        if self._n <= self._n_actions:
            return 'Thought: 需要工具\n<action>echo({"v": 1})</action>'
        return "Final Answer: 完成"

    @property
    def last_messages(self) -> list[dict]:
        return self.calls[-1]

    @staticmethod
    def user_contents(messages: list[dict]) -> list[str]:
        return [m["content"] for m in messages if m["role"] == "user"]


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

    def test_observation_comes_after_task(self):
        """Observation 追加在 task 之后（任务为第一条 user 消息）。"""
        scripted = ScriptedLLM(n_actions=1)
        agent = _agent(scripted)
        agent.run(agent.build_system_prompt(), "任务")
        users = scripted.user_contents(scripted.last_messages)
        assert "Observation" in users[-1]
        assert scripted.last_messages[1]["content"] == "任务"


class TestObservationTruncation:
    def test_long_observation_truncated(self):
        """单条 Observation 截断到 obs_max_chars，并带截断标记（原文不再完整出现）。"""
        long = "x" * 5000
        scripted = ScriptedLLM(n_actions=1)
        agent = _agent(scripted, tool_output=long)
        agent.run(agent.build_system_prompt(), "任务", obs_max_chars=100)
        users = scripted.user_contents(scripted.last_messages)
        obs = next(c for c in users if "Observation" in c)
        assert "（内容过长已截断）" in obs
        assert long not in obs  # 完整原文被截断，不再入上下文

    def test_short_observation_not_truncated(self):
        scripted = ScriptedLLM(n_actions=1)
        agent = _agent(scripted, tool_output="short")
        agent.run(agent.build_system_prompt(), "任务", obs_max_chars=100)
        users = scripted.user_contents(scripted.last_messages)
        obs = next(c for c in users if "Observation" in c)
        assert "short" in obs
        assert "截断" not in obs


class TestHistoryCompression:
    def test_history_bounded_after_many_steps(self):
        """工具步超过 max_history_steps 后消息数被压缩到有界。"""
        scripted = ScriptedLLM(n_actions=10)
        agent = _agent(scripted)
        agent.run(
            agent.build_system_prompt(),
            "任务",
            max_steps=12,
            max_history_steps=2,
        )
        assert len(scripted.last_messages) <= 2 + 2 * 2  # system + task + 2 步
        # 压缩后仍保留首条任务（消息位置 1）
        assert scripted.last_messages[1]["content"] == "任务"
        # 最新 Observation 仍保留（最后一条 user 消息）
        users = scripted.user_contents(scripted.last_messages)
        assert "Observation" in users[-1]

    def test_no_compression_under_limit(self):
        scripted = ScriptedLLM(n_actions=1)
        agent = _agent(scripted)
        agent.run(agent.build_system_prompt(), "任务", max_history_steps=8)
        # 1 步 = system + task + assistant + obs = 4 条，未达压缩线
        assert len(scripted.last_messages) == 4

    def test_default_constants(self):
        assert _OBS_MAX_CHARS == 4000
        assert _MAX_HISTORY_STEPS == 8

    def test_compress_history_keeps_task_and_recent(self):
        """_compress_history 直接单测：保留 system + task + 最近 2*N 条。"""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "任务"},
        ]
        for i in range(6):
            messages.append({"role": "assistant", "content": f"assist{i}"})
            messages.append({"role": "user", "content": f"obs{i}"})
        out = ReactAgent._compress_history(messages, max_history_steps=2)
        assert len(out) == 6
        assert out[0] == {"role": "system", "content": "sys"}
        assert out[1] == {"role": "user", "content": "任务"}
        # 保留最近 2 步（obs4/obs5），丢弃最旧
        assert out[-1]["content"] == "obs5"
        assert "obs0" not in [m["content"] for m in out]
