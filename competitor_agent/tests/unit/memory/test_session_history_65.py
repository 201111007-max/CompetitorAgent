"""设计文档 65 §3 — 多轮会话历史（SessionHistory）+ 长期压缩 + 注入链路单测。

覆盖：
① §3.2 append/messages/raw/drop/has 持久化（JsonStore 落盘，重开实例可读）；
② §3.4 窗口保留 + 远端折叠（近端原文可指代，远端 [摘要]）；总量上限截断；
③ 角色交替（首条 user、相邻不重复、末尾 assistant；悬空 user 有前文时丢弃，
   单条 user 历史保留）；
④ §3.4 LRU 淘汰（max_sessions 防无界磁盘）；
⑤ §3.3 注入链路：ReactAgent.run(history_messages=...) → LLM messages
   为 [system, *history, user]；history=None 行为不变；
⑥ 同 session_id 长期控制持续生效（第 15 轮仍见第 1 轮摘要）。
"""
from __future__ import annotations

from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.llm.client import LLMClient, ToolCallReply
from competitor_agent.memory.session_history import SessionHistory


def _append_rounds(hist: SessionHistory, sid: str, n: int, prefix: str = "轮") -> None:
    for i in range(1, n + 1):
        hist.append(sid, "user", f"{prefix}{i}：用户第{i}轮的问题内容")
        hist.append(sid, "assistant", f"{prefix}{i}：助手对第{i}轮的回答内容")


class TestSessionHistoryBasics:
    def test_append_and_messages(self, tmp_path):
        h = SessionHistory(data_dir=tmp_path, max_verbatim_turns=10)
        h.append("s1", "user", "第一轮问题")
        h.append("s1", "assistant", "第一轮回答")
        msgs = h.messages("s1")
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert msgs[0]["content"] == "第一轮问题"
        assert msgs[1]["content"] == "第一轮回答"

    def test_append_ignores_unknown_role(self, tmp_path):
        h = SessionHistory(data_dir=tmp_path)
        h.append("s1", "tool", "ignored")
        assert h.messages("s1") == []

    def test_persistence_across_instances(self, tmp_path):
        h1 = SessionHistory(data_dir=tmp_path)
        h1.append("s1", "user", "q")
        h1.append("s1", "assistant", "a")
        h2 = SessionHistory(data_dir=tmp_path)
        assert h2.has("s1")
        assert [m["content"] for m in h2.messages("s1")] == ["q", "a"]

    def test_drop_clears(self, tmp_path):
        h = SessionHistory(data_dir=tmp_path)
        h.append("s1", "user", "q")
        h.drop("s1")
        assert not h.has("s1")
        assert h.messages("s1") == []

    def test_raw_includes_ts(self, tmp_path):
        h = SessionHistory(data_dir=tmp_path)
        h.append("s1", "user", "q")
        raw = h.raw("s1")
        assert len(raw) == 1
        assert "ts" in raw[0]
        assert raw[0]["content"] == "q"


class TestLongTermCompression:
    def test_window_keeps_recent_verbatim_folds_old(self, tmp_path):
        """§3.4：最近 max_verbatim_turns 轮原文，更早轮折叠为 [摘要]。"""
        h = SessionHistory(data_dir=tmp_path, max_verbatim_turns=3, max_history_chars=10**6)
        _append_rounds(h, "s1", 6)  # 6 轮 = 12 条
        msgs = h.messages("s1")
        assert len(msgs) == 12
        summarized = [m for m in msgs if m["content"].startswith("[摘要]")]
        verbatim = [m for m in msgs if not m["content"].startswith("[摘要]")]
        # 6 轮 - 3 窗口 = 3 轮折叠 = 6 条摘要；窗口 3 轮 = 6 条原文
        assert len(summarized) == 6
        assert len(verbatim) == 6
        # 最近一轮原文保留（可指代"上一轮"）
        assert msgs[-1]["content"] == "轮6：助手对第6轮的回答内容"

    def test_long_session_keeps_first_round_folded_summary(self, tmp_path):
        """§5.4：同 session_id 长期控制持续生效——第 15 轮仍收到第 1 轮的折叠摘要。"""
        h = SessionHistory(data_dir=tmp_path, max_verbatim_turns=10, max_history_chars=10**6)
        _append_rounds(h, "s1", 15)
        msgs = h.messages("s1")
        # 15 轮 - 10 窗口 = 5 轮折叠 = 10 条摘要
        assert any(m["content"].startswith("[摘要]") and "轮1" in m["content"] for m in msgs)
        # 最近窗口原文
        assert msgs[-1]["content"] == "轮15：助手对第15轮的回答内容"

    def test_total_char_cap(self, tmp_path):
        """§3.4 总量上限：注入消息总字符 ≤ max_history_chars（含单条溢出标记余量）。"""
        h = SessionHistory(data_dir=tmp_path, max_verbatim_turns=10, max_history_chars=300)
        _append_rounds(h, "s1", 6)
        msgs = h.messages("s1")
        total = sum(len(m["content"]) for m in msgs)
        assert total <= 300 + 60
        assert msgs[-1]["role"] == "assistant"

    def test_new_session_starts_empty(self, tmp_path):
        """§3.4/§5.4：点"新会话"= 新 session_id → 历史从空开始（断开长期控制）。"""
        h = SessionHistory(data_dir=tmp_path)
        _append_rounds(h, "s_old", 5)
        assert h.messages("s_new") == []
        assert not h.has("s_new")


class TestRoleAlternation:
    def test_single_user_kept(self, tmp_path):
        """单条 user 历史（首问未答）保留——可被重新问起的有效首轮。"""
        h = SessionHistory(data_dir=tmp_path)
        h.append("s1", "user", "hello")
        msgs = h.messages("s1")
        assert [m["role"] for m in msgs] == ["user"]
        assert msgs[-1]["content"] == "hello"

    def test_dangling_user_with_context_dropped(self, tmp_path):
        """有前文的末尾悬空 user（上轮被中断）→ 丢弃，末尾收敛为 assistant。"""
        h = SessionHistory(data_dir=tmp_path)
        h.append("s1", "user", "q1")
        h.append("s1", "assistant", "a1")
        h.append("s1", "user", "q2")  # 无 assistant 收尾
        msgs = h.messages("s1")
        assert msgs[-1]["role"] == "assistant"
        assert [m["content"] for m in msgs] == ["q1", "a1"]

    def test_adjacent_duplicate_roles_deduped(self, tmp_path):
        h = SessionHistory(data_dir=tmp_path)
        h.append("s1", "user", "q1")
        h.append("s1", "user", "q2")  # 异常相邻（正常调用不会发生，防脏数据）
        h.append("s1", "assistant", "a1")
        msgs = h.messages("s1")
        roles = [m["role"] for m in msgs]
        assert all(roles[i] != roles[i + 1] for i in range(len(roles) - 1))
        assert roles[0] == "user" and roles[-1] == "assistant"


class TestLruEviction:
    def test_max_sessions_evicts_oldest_unused(self, tmp_path):
        h = SessionHistory(data_dir=tmp_path, max_sessions=3)
        for i in range(6):
            h.append(f"sid{i}", "user", f"task{i}")
        keys = set(h._store.keys())
        assert len(keys) <= 3
        assert "sid0" not in keys
        assert "sid5" in keys


class _CaptureLLM:
    """捕获传入 LLM 的 messages（脚本化直接收尾，无工具调用）。"""

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    def __call__(self, messages, model=None, **kwargs):
        self.calls.append(list(messages))
        return ToolCallReply(content="最终回答", tool_calls=None)


class TestInjectionChain:
    def test_history_messages_injected_before_user(self):
        capture = _CaptureLLM()
        agent = ReactAgent(llm=LLMClient(call_func=capture), dispatcher=ToolDispatcher())
        history = [
            {"role": "user", "content": "上一轮问题：为什么维度结论是 JSON"},
            {"role": "assistant", "content": "上一轮回答：因为解析严格失败"},
        ]
        agent.run("你是竞品情报分析 Agent。", "用代码分析我刚才提到的问题", max_steps=1, history_messages=history)
        msgs = capture.calls[0]
        assert msgs[0]["role"] == "system"
        assert msgs[-1] == {"role": "user", "content": "用代码分析我刚才提到的问题"}
        # history 以 user/assistant 对出现在 system 与当前 user 之间
        assert msgs[1] == {"role": "user", "content": "上一轮问题：为什么维度结论是 JSON"}
        assert msgs[2] == {"role": "assistant", "content": "上一轮回答：因为解析严格失败"}

    def test_history_none_unchanged(self):
        """§3.5 回归：history=None（既有调用方）行为逐字节不变。"""
        capture = _CaptureLLM()
        agent = ReactAgent(llm=LLMClient(call_func=capture), dispatcher=ToolDispatcher())
        answer = agent.run("你是竞品情报分析 Agent。", "普通问题", max_steps=1)
        assert answer == "最终回答"
        msgs = capture.calls[0]
        assert [m["role"] for m in msgs] == ["system", "user"]
        assert msgs[-1]["content"] == "普通问题"

    def test_history_empty_list_unchanged(self):
        capture = _CaptureLLM()
        agent = ReactAgent(llm=LLMClient(call_func=capture), dispatcher=ToolDispatcher())
        agent.run("你是竞品情报分析 Agent。", "问题", max_steps=1, history_messages=[])
        msgs = capture.calls[0]
        assert [m["role"] for m in msgs] == ["system", "user"]

    def test_end_to_end_two_rounds_same_session(self, tmp_path):
        """§5.3 多轮回灌：同 session_id 两轮，第二轮 messages 含第一轮 user/assistant 对。"""
        h = SessionHistory(data_dir=tmp_path, max_verbatim_turns=10)
        h.append("s1", "user", "第一轮：为什么维度结论是 JSON")
        h.append("s1", "assistant", "第一轮：解析严格失败")
        history = h.messages("s1")
        assert len(history) == 2
        capture = _CaptureLLM()
        agent = ReactAgent(llm=LLMClient(call_func=capture), dispatcher=ToolDispatcher())
        agent.run(
            "你是竞品情报分析 Agent。",
            "用代码分析我刚才提到的问题",
            max_steps=1,
            history_messages=history,
        )
        msgs = capture.calls[0]
        assert msgs[1]["content"] == "第一轮：为什么维度结论是 JSON"
        assert msgs[2]["content"] == "第一轮：解析严格失败"
