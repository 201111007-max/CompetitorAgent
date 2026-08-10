"""问题 4 修复测试：Web 取消 session_id 断链 + 协作式取消真正中断

覆盖设计文档 04 验证方式：
- 单元：analyze(session_id="x") 内部取消标志与外传 id 一致
- 集成：慢速分析中调用 cancel，循环提前终止并返回部分结果
- 协作式：TacticalLoop 每轮迭代感知取消、多 Agent 采集阶段感知取消
"""
from __future__ import annotations

import threading
import time

from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.core.budget import IterationBudget
from competitor_agent.core.checkpoint import (
    clear_cancel,
    delete_checkpoint,
    is_cancelled,
    load_checkpoint,
    set_cancel,
)
from competitor_agent.core.competitor_registry import COMPETITOR_REGISTRY
from competitor_agent.core.tactical_loop import TacticalLoop
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation, SourceEvidence
from competitor_agent.domain_types.report import CancelledResult, CompetitorReport
from competitor_agent.domain_types.strategy import CompetitorStrategy
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.interfaces.context import SourceContext
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError

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


def _api(**kwargs):
    return CompetitorAnalysisAPI(extractor=FakeExtractor(), use_llm=False, **kwargs)


class TestSessionIdConsistency:
    def test_passed_session_id_drives_internal_cancel_flag(self):
        # 预置取消标志：若 analyze 内部仍用自生成 uuid，则此处取消不会生效
        set_cancel("sess_probe_1")
        try:
            report = _api().analyze("分析 Cursor", mode="single", session_id="sess_probe_1")
            assert isinstance(report, CancelledResult)
            assert report.cancelled is True
            assert report.terminal_state == "cancelled"
        finally:
            clear_cancel("sess_probe_1")

    def test_default_session_id_not_cancelled(self):
        report = _api().analyze("分析 Cursor", mode="single", session_id="sess_probe_2")
        assert isinstance(report, CompetitorReport)
        assert not isinstance(report, CancelledResult)
        assert report.dimension_results

    def test_cancel_api_sets_flag_for_reused_id(self):
        api = _api()
        api.cancel("sess_probe_3")
        try:
            assert is_cancelled("sess_probe_3")
            report = api.analyze("分析 Cursor", mode="single", session_id="sess_probe_3")
            assert isinstance(report, CancelledResult)
        finally:
            clear_cancel("sess_probe_3")

    def test_team_mode_cancel_propagates(self):
        set_cancel("sess_probe_team")
        try:
            report = _api().analyze("分析 Cursor", mode="team", session_id="sess_probe_team")
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
    def test_cancel_during_run_returns_partial_result_and_stops(self):
        sid = "sess_partial_1"
        blocking = threading.Event()
        api = CompetitorAnalysisAPI(
            extractor=_SlowExtractor(sid, blocking),
            use_llm=False,
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

    def test_tactical_loop_stops_within_iteration_on_cancel(self):
        sid = "sess_loop_1"

        class SetCancelThenFailExtractor:
            def __init__(self) -> None:
                self.calls = 0

            def fetch(self, gap: InfoGap, context: SourceContext) -> Observation:
                self.calls += 1
                set_cancel(sid)  # 首次采集时触发取消（模拟 Web 取消）
                raise DataSourceUnavailableError("源不可用")

        extractor = SetCancelThenFailExtractor()
        strategy = CompetitorStrategy(
            competitor=COMPETITOR_REGISTRY["cursor"],
            gaps=[InfoGap(field="pricing")],
        )
        loop = TacticalLoop(
            selector=SourceSelector(),
            extractor=extractor,
            analyzer=_StubAnalyzer(),
            budget=IterationBudget(max_iterations=10, cost_limit=1.0),
            session_id=sid,
        )
        try:
            result = loop.execute(strategy.gaps[0], strategy)
            assert result is None  # 取消后立即终止，不继续降级链
            assert extractor.calls == 1  # 第二个候选源未被尝试
        finally:
            clear_cancel(sid)

    def test_tactical_loop_without_session_id_never_checks_cancel(self):
        # 未传 session_id 时保持原行为：多候选源全部尝试
        sid = "sess_loop_noop"

        class FlakyExtractor:
            def __init__(self) -> None:
                self.calls = 0

            def fetch(self, gap: InfoGap, context: SourceContext) -> Observation:
                self.calls += 1
                if self.calls == 1:
                    raise DataSourceUnavailableError("源不可用")
                return FakeExtractor().fetch(gap, context)

        extractor = FlakyExtractor()
        strategy = CompetitorStrategy(
            competitor=COMPETITOR_REGISTRY["cursor"],
            gaps=[InfoGap(field="pricing")],
        )
        loop = TacticalLoop(
            selector=SourceSelector(),
            extractor=extractor,
            analyzer=_StubAnalyzer(),
            budget=IterationBudget(max_iterations=10, cost_limit=1.0),
            session_id=None,
        )
        try:
            result = loop.execute(strategy.gaps[0], strategy)
            assert result is not None  # 降级到第二个源成功闭环
            assert extractor.calls >= 2
        finally:
            clear_cancel(sid)


class _StubAnalyzer:
    """最小分析器桩：测试中不会被实际调用（采集已失败/取消）"""

    dimension = "pricing"

    def analyze(self, observation, gap, context):
        from competitor_agent.domain_types.report import DimensionResult

        return DimensionResult(dimension="pricing", summary="", confidence=0.0)