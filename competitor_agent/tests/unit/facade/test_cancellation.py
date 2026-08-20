"""问题 4 修复测试：Web 取消 session_id 断链 + 协作式取消真正中断（设计文档 04/49）

- 单元：analyze(session_id="x") 内部取消标志与外传 id 一致
- 集成：慢速分析中调用 cancel，循环提前终止并返回部分结果
- 协作式（49 迁移）：ReactLoop._step_guard 每步感知取消；无 session_id 不感知
"""
from __future__ import annotations

import threading
import time

from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.agent.react_loop import ReactLoop
from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.config.loader import AppConfig, CollectorConfig
from competitor_agent.core.checkpoint import (
    clear_cancel,
    delete_checkpoint,
    is_cancelled,
    load_checkpoint,
    set_cancel,
)
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation, SourceEvidence
from competitor_agent.domain_types.report import CancelledResult, CompetitorReport
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.interfaces.context import SourceContext
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError
from competitor_agent.llm.client import LLMClient

CURSOR_PRICING = "Pro $20/month\nTeams $40/month\nUltra $60/month"


class FakeExtractor:
    def fetch(self, gap: InfoGap, context: SourceContext) -> Observation:
        url = str(context.kwargs.get("url"))
        if "pricing" in url:
            text = CURSOR_PRICING
        elif "docs" in url or "cursor.com" in url:
            text = "Cursor supports MCP integration, agent mode, and Codex-style reviews."
        else:
            text = "Cursor is an AI code editor."
        ev = SourceEvidence(source_name="web_extractor", url=url, content_hash=str(hash(url)), trust_level=0.9)
        return Observation(gap_field=gap.field, source="web_extractor", raw_text=text, evidence=ev)


def _api(llm, **kwargs):
    # 关闭 URL 守卫（DNS 解析离线必败）：让测试注入的 FakeExtractor 真实被 web_extract 调用
    cfg = AppConfig(collector=CollectorConfig(block_private_urls=False))
    return CompetitorAnalysisAPI(extractor=FakeExtractor(), llm=llm, use_llm=True, config=cfg, **kwargs)


class TestSessionIdConsistency:
    def test_passed_session_id_drives_internal_cancel_flag(self, mock_llm):
        # 预置取消标志：若 analyze 内部仍用自生成 uuid，则此处取消不会生效
        set_cancel("sess_probe_1")
        try:
            report = _api(mock_llm).analyze("分析 Cursor", mode="single", session_id="sess_probe_1")
            assert isinstance(report, CancelledResult)
            assert report.cancelled is True
            assert report.terminal_state == "cancelled"
        finally:
            clear_cancel("sess_probe_1")

    def test_default_session_id_not_cancelled(self, mock_llm):
        report = _api(mock_llm).analyze("分析 Cursor", mode="single", session_id="sess_probe_2")
        assert isinstance(report, CompetitorReport)
        assert not isinstance(report, CancelledResult)
        assert report.dimension_results

    def test_cancel_api_sets_flag_for_reused_id(self, mock_llm):
        api = _api(mock_llm)
        api.cancel("sess_probe_3")
        try:
            assert is_cancelled("sess_probe_3")
            report = api.analyze("分析 Cursor", mode="single", session_id="sess_probe_3")
            assert isinstance(report, CancelledResult)
        finally:
            clear_cancel("sess_probe_3")

    def test_team_mode_cancel_propagates(self, mock_llm):
        set_cancel("sess_probe_team")
        try:
            report = _api(mock_llm).analyze("分析 Cursor", mode="team", session_id="sess_probe_team")
            assert isinstance(report, CancelledResult)
            assert report.cancelled is True
            assert report.terminal_state == "cancelled"
        finally:
            clear_cancel("sess_probe_team")


class _SlowExtractor:
    """首个缺口立即成功（产出部分结果 + checkpoint），后续采集阻塞感知取消后抛源不可用"""

    def __init__(self, sid: str, blocking: threading.Event) -> None:
        self._sid = sid
        self._blocking = blocking
        self._calls = 0
        self._base = FakeExtractor()

    def fetch(self, gap: InfoGap, context: SourceContext) -> Observation:
        self._calls += 1
        if self._calls > 1:
            self._blocking.set()
            while not is_cancelled(self._sid):
                time.sleep(0.005)
            raise DataSourceUnavailableError("会话已取消，停止采集")
        return self._base.fetch(gap, context)


class TestCooperativeCancellation:
    def test_cancel_during_run_returns_partial_result_and_stops(self, mock_llm):
        sid = "sess_partial_1"
        blocking = threading.Event()
        cfg = AppConfig(collector=CollectorConfig(block_private_urls=False))
        api = CompetitorAnalysisAPI(
            extractor=_SlowExtractor(sid, blocking),
            llm=mock_llm,
            use_llm=True,
            config=cfg,
        )

        result_holder: list[CompetitorReport] = []

        def _run() -> None:
            result_holder.append(api.analyze("分析 Cursor", mode="single", session_id=sid))

        t = threading.Thread(target=_run)
        t.start()
        try:
            assert blocking.wait(timeout=10), "分析未进入慢速采集阶段"
            set_cancel(sid)
            t.join(timeout=15)
            assert not t.is_alive(), "取消后分析线程仍在运行（假取消）"
            report = result_holder[0]
            assert isinstance(report, CancelledResult)
            assert report.cancelled is True
            assert report.terminal_state == "cancelled"
            # 部分结果：第一个缺口已闭环
            assert len(report.dimension_results) >= 1
            # checkpoint 保留（供 /resume 续跑）
            assert load_checkpoint(sid) is not None
        finally:
            clear_cancel(sid)
            delete_checkpoint(sid)


class TestReactLoopCooperativeCancellation:
    """设计文档 49 迁移：取消感知内化到 ReactLoop._step_guard（原 TacticalLoop 语义）。"""

    @staticmethod
    def _loop(sid: str | None):
        called = {"n": 0}

        def fake_llm(messages, model):
            called["n"] += 1
            return "Final Answer: done"

        agent = ReactAgent(
            llm=LLMClient(call_func=fake_llm),
            dispatcher=ToolDispatcher(tools={}),
            protocol="react",
        )
        loop = ReactLoop(agent, session_id=sid, plan_first=False)
        loop._called = called  # type: ignore[attr-defined]
        return loop, called

    def test_react_loop_cancelled_before_start(self):
        sid = "sess_loop_react_1"
        loop, called = self._loop(sid)
        set_cancel(sid)
        try:
            result = loop.run_with_result("分析 cursor")
            assert result.cancelled is True
            assert result.steps == 0
            assert called["n"] == 0, "取消后不发起任何 LLM 调用"
        finally:
            clear_cancel(sid)

    def test_react_loop_without_session_id_runs(self):
        loop, called = self._loop(None)
        result = loop.run_with_result("分析 cursor")
        assert result.cancelled is False
        assert called["n"] >= 1
        assert "done" in result.answer
