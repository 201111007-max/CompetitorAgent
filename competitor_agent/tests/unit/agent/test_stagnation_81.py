"""设计文档 81：停滞检测——ADR 演进式补充的单测与评测用例。

自然收敛（max_steps=None）保留为主路径；本组验证「客观收敛信号」：
signature 重复触发 / 结果重复率触发 / 提示上限 2 次 / 分页不误触 / ignore_arg_keys /
ReactLoop 注入与 progress 事件 / 预算耗尽 → partial（评测用例闭环）。
"""

from __future__ import annotations

from typing import Any

from competitor_agent.agent.stagnation import StagnationConfig, StagnationDetector
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.llm.client import ToolCall, ToolCallReply


class TestDetectorUnit:
    def test_signature_repeat_triggers(self) -> None:
        detector = StagnationDetector(StagnationConfig(sig_repeat=3, window=8))
        assert detector.record_round([("web_search", {"query": "cursor 价格"}, "结果一")]) is None
        assert detector.record_round([("web_search", {"query": "cursor 价格"}, "结果二")]) is None
        hint = detector.record_round([("web_search", {"query": "cursor 价格"}, "结果三")])
        assert hint is not None and "高度重复" in hint
        assert detector.hints_issued == 1

    def test_dup_rate_two_consecutive_rounds_triggers(self) -> None:
        detector = StagnationDetector(StagnationConfig(sig_repeat=3, window=8, dup_threshold=0.5))
        # 同义改写（tokenize 高度重叠）但参数不同 → 不命中签名条件，命中重复率条件
        assert detector.record_round([("web_extract", {"url": "https://a/1"}, "Cursor 支持终端运行 与 MCP 协议")]) is None
        assert detector.record_round([("web_extract", {"url": "https://a/2"}, "Cursor 支持终端运行 与 MCP 协议!")]) is None
        hint = detector.record_round([("web_extract", {"url": "https://a/3"}, "Cursor 支持终端运行 与 MCP 协议…")])
        assert hint is not None

    def test_pagination_does_not_false_trigger(self) -> None:
        """正常连续翻页：参数不同、内容不同 → 不误触（doc 81 §4 风险缓解）。"""
        detector = StagnationDetector(StagnationConfig(sig_repeat=3, window=8))
        for page in range(1, 9):
            hint = detector.record_round(
                [("web_extract", {"url": f"https://a/list?page={page}"}, f"第 {page} 页内容：条目 {page}A {page}B {page}C")]
            )
            assert hint is None, f"page={page} 误触停滞"

    def test_ignore_arg_keys_noise(self) -> None:
        """args 仅差时间戳类噪声键 → 视为同签名（doc 81 §4：ignore_arg_keys 生效）。"""
        detector = StagnationDetector(StagnationConfig(sig_repeat=3, window=8, ignore_arg_keys=("ts",)))
        detector.record_round([("web_search", {"query": "q", "ts": 1}, "结果一")])
        detector.record_round([("web_search", {"query": "q", "ts": 2}, "结果二")])
        hint = detector.record_round([("web_search", {"query": "q", "ts": 3}, "结果三")])
        assert hint is not None

    def test_max_hints_two_then_silent(self) -> None:
        """doc 81 §2.2：提示最多 2 次（第 2 次为警示文案），此后不再注入。"""
        detector = StagnationDetector(StagnationConfig(sig_repeat=2, window=8, max_hints=2))
        kinds: list[str] = []
        detector._on_hint = lambda kind, evidence: kinds.append(kind)
        # sig_repeat=2：第 2 次重复触发 hint，第 3 次触发改发警示，第 4 次静默
        assert detector.record_round([("t", {"q": 1}, "a")]) is None
        first = detector.record_round([("t", {"q": 1}, "a")])
        second = detector.record_round([("t", {"q": 1}, "a")])
        third = detector.record_round([("t", {"q": 1}, "a")])
        assert first and "高度重复" in first
        assert second and "收尾" in second  # 警示文案
        assert third is None  # 上限已到
        assert kinds == ["hint", "warn"]

    def test_disabled_never_triggers(self) -> None:
        detector = StagnationDetector(StagnationConfig(enabled=False, sig_repeat=1))
        for _ in range(5):
            assert detector.record_round([("t", {"q": 1}, "同一结果")] ) is None


class _FakeDispatcher:
    def dispatch(self, name: str, args: dict | None = None) -> str:
        return f"工具 {name} 的固定结果内容"


class _ScriptedLLM:
    """前 N 轮重复同一工具调用，随后收尾；记录每轮消息供注入断言。"""

    def __init__(self, repeat_rounds: int = 4, tool: str = "web_search") -> None:
        self._repeat = repeat_rounds
        self._tool = tool
        self.rounds: list[list[dict[str, Any]]] = []
        self._step = 0

    def complete_with_tools(self, messages, tools, tool_choice=None, **kwargs: object) -> ToolCallReply:
        self.rounds.append([dict(m) for m in messages])
        self._step += 1
        if self._step <= self._repeat:
            return ToolCallReply(
                tool_calls=[ToolCall(id=f"c{self._step}", name=self._tool, arguments={"query": "cursor 价格"})]
            )
        return ToolCallReply(content='{"competitor": "cursor", "dimensions": []}')

    def complete(self, messages, json_mode: bool = False) -> str:  # pragma: no cover
        return "{}"


class TestReactLoopIntegration:
    def test_stagnation_hint_injected_and_run_completes(self) -> None:
        """停滞触发 → system 提示进消息流 → LLM 收尾；progress 事件发出。"""
        from competitor_agent.agent.react_agent import ReactAgent
        from competitor_agent.agent.react_loop import ReactLoop

        llm = _ScriptedLLM(repeat_rounds=4)
        events: list[ProgressEvent] = []
        loop = ReactLoop(
            ReactAgent(llm=llm, dispatcher=_FakeDispatcher()),  # type: ignore[arg-type]
            max_steps=8,
            event_sink=events.append,
            stagnation=StagnationConfig(sig_repeat=3, window=8, max_hints=2),
        )
        result = loop.run_with_result("只分析 cursor 的定价")
        assert '{"competitor": "cursor"' in result.answer
        hinted = [
            msgs for msgs in llm.rounds
            if any(m.get("role") == "system" and "高度重复" in str(m.get("content", "")) for m in msgs)
        ]
        assert hinted, "收敛提示未注入消息流"
        assert len(hinted) <= 2  # 提示上限
        assert any(e.phase == "stagnation" for e in events), "停滞 progress 事件未发出"

    def test_disabled_no_injection(self) -> None:
        from competitor_agent.agent.react_agent import ReactAgent
        from competitor_agent.agent.react_loop import ReactLoop

        llm = _ScriptedLLM(repeat_rounds=6)
        loop = ReactLoop(
            ReactAgent(llm=llm, dispatcher=_FakeDispatcher()),  # type: ignore[arg-type]
            max_steps=10,
            stagnation=StagnationConfig(enabled=False),
        )
        loop.run_with_result("任务")
        hinted = [
            msgs for msgs in llm.rounds
            if any(m.get("role") == "system" and "收敛" in str(m.get("content", "")) for m in msgs)
        ]
        assert not hinted
        assert loop._stagnation.hints_issued == 0


class TestBudgetExhaustedPartial:
    """doc 81 §5 评测用例：预算耗尽 → partial 报告并标注完成度（被评测保证的行为）。

    Lead 循环预算经 ReactLoop budget 传入（iteration 级 consume，doc 43 语义）；
    耗尽后 terminal=partial，报告正文标注终态且 gaps_pending 可审计。
    """

    def test_budget_exhausted_yields_partial_with_completion_markers(self) -> None:
        from competitor_agent.agent.react_agent import ReactAgent
        from competitor_agent.agent.react_loop import ReactLoop
        from competitor_agent.core.budget import IterationBudget
        from competitor_agent.core.report_builder import ReportBuilder
        from competitor_agent.domain_types.competitor import Competitor
        from competitor_agent.facade import react_report

        budget = IterationBudget(max_iterations=2)
        loop = ReactLoop(
            ReactAgent(llm=_ScriptedLLM(repeat_rounds=6), dispatcher=_FakeDispatcher()),  # type: ignore[arg-type]
            max_steps=10,
            budget=budget,
        )
        result = loop.run_with_result("只分析 cursor 的定价")
        assert result.budget_exhausted
        report = react_report.assemble(
            lead_answer=result.answer,
            competitor=Competitor(name="cursor"),
            loop_plan=None,
            transcript=result.transcript,
            builder=ReportBuilder(),
            terminal_state="partial",
        )
        assert report.terminal_state == "partial"
        assert "partial" in report.markdown_report
        assert isinstance(report.gaps_pending, list)
