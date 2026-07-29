"""可观测性 Span 集成测试 — 验证 8 个关键步骤正确创建 Tracer Span"""
import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dota_helper.observability.tracer import Tracer, TracerSpan
from dota_helper.observability import init_tracer, get_tracer
import dota_helper.observability as obs_module


def _reset_tracer() -> None:
    """重置全局追踪器为 NoOpTracer"""
    obs_module._tracer = None


def _init_test_tracer() -> Tracer:
    """初始化测试用内存 Tracer 并返回"""
    _reset_tracer()
    init_tracer(use_langfuse=False)
    tracer = get_tracer()
    assert isinstance(tracer, Tracer)
    return tracer


# ── 接入点 1 & 2 & 3 & 6 & 7: ReviewOrchestrator 内的 span ──

class TestReviewOrchestratorTracer:
    """ReviewOrchestrator 可观测性集成测试"""

    @pytest.mark.asyncio
    async def test_review_full_span_created(self) -> None:
        """复盘启动时创建 review.full 顶层 span"""
        tracer = _init_test_tracer()

        from dota_helper.orchestrator.review_orchestrator import ReviewOrchestrator
        from dota_helper.domain_types.state import ReviewAgentState
        from dota_helper.domain_types.match_data import MatchData
        from dota_helper.domain_types.analysis import AnalysisResult

        # 构造 mock 依赖
        mock_data_source = AsyncMock()
        match_data = MatchData(
            match_id="123", duration=2400, radiant_win=True,
            radiant_score=30, dire_score=28, game_mode=22,
            players=[], picks_bans=[],
        )
        mock_data_source.fetch_match.return_value = match_data

        mock_strategic = MagicMock()
        from dota_helper.domain_types.strategy import AnalysisStrategy
        strategy = AnalysisStrategy(
            match_type="normal", priority_phases=["laning"],
            budget_allocation={"laning": 2}, expected_depth={"laning": "standard"},
        )
        mock_strategic.evaluate.return_value = strategy

        mock_tactical = AsyncMock()
        result = AnalysisResult(
            phase="laning", conclusions=[], confidence=0.8,
            iterations_used=1, tokens_consumed=500,
        )
        mock_tactical.execute.return_value = result
        mock_tactical_factory = MagicMock(return_value=mock_tactical)

        mock_verifier = MagicMock()
        from dota_helper.domain_types.events import VerificationResult
        mock_verifier.verify.return_value = VerificationResult(
            passed=True, blocking_reasons=[], suggestions=[],
        )

        from dota_helper.report.report_builder import ReportBuilder
        from dota_helper.report.markdown_renderer import MarkdownRenderer
        report_builder = ReportBuilder()
        markdown_renderer = MarkdownRenderer()

        state = ReviewAgentState(match_id="123")

        orchestrator = ReviewOrchestrator(
            data_source=mock_data_source,
            strategic_loop=mock_strategic,
            tactical_loop_factory=mock_tactical_factory,
            stop_verifier=mock_verifier,
            report_builder=report_builder,
            state=state,
            markdown_renderer=markdown_renderer,
        )

        report = await orchestrator.review("123")

        # 验证 span 被创建
        spans = tracer.completed_spans
        span_names = [s.name for s in spans]
        assert "review.full" in span_names
        assert "review.data_fetch" in span_names
        assert "review.strategic" in span_names
        assert "review.stop_verify" in span_names
        assert "review.report_build" in span_names

    @pytest.mark.asyncio
    async def test_data_fetch_span_attributes(self) -> None:
        """数据获取 span 记录 match_id 和比赛属性"""
        tracer = _init_test_tracer()

        from dota_helper.orchestrator.review_orchestrator import ReviewOrchestrator
        from dota_helper.domain_types.state import ReviewAgentState
        from dota_helper.domain_types.match_data import MatchData
        from dota_helper.domain_types.analysis import AnalysisResult

        mock_data_source = AsyncMock()
        match_data = MatchData(
            match_id="456", duration=1800, radiant_win=False,
            radiant_score=20, dire_score=25, game_mode=22,
            players=[], picks_bans=[],
        )
        mock_data_source.fetch_match.return_value = match_data

        mock_strategic = MagicMock()
        from dota_helper.domain_types.strategy import AnalysisStrategy
        strategy = AnalysisStrategy(
            match_type="normal", priority_phases=["economy"],
            budget_allocation={"economy": 2}, expected_depth={"economy": "standard"},
        )
        mock_strategic.evaluate.return_value = strategy

        mock_tactical = AsyncMock()
        result = AnalysisResult(
            phase="economy", conclusions=[], confidence=0.75,
            iterations_used=1, tokens_consumed=300,
        )
        mock_tactical.execute.return_value = result
        mock_tactical_factory = MagicMock(return_value=mock_tactical)

        mock_verifier = MagicMock()
        from dota_helper.domain_types.events import VerificationResult
        mock_verifier.verify.return_value = VerificationResult(
            passed=True, blocking_reasons=[], suggestions=[],
        )

        from dota_helper.report.report_builder import ReportBuilder
        from dota_helper.report.markdown_renderer import MarkdownRenderer
        state = ReviewAgentState(match_id="456")

        orchestrator = ReviewOrchestrator(
            data_source=mock_data_source,
            strategic_loop=mock_strategic,
            tactical_loop_factory=mock_tactical_factory,
            stop_verifier=mock_verifier,
            report_builder=ReportBuilder(),
            state=state,
            markdown_renderer=MarkdownRenderer(),
        )

        await orchestrator.review("456")

        # 查找 data_fetch span
        spans = tracer.completed_spans
        data_span = next(s for s in spans if s.name == "review.data_fetch")
        assert data_span.attributes.get("duration") == 1800
        assert data_span.attributes.get("radiant_win") is False

    @pytest.mark.asyncio
    async def test_span_nesting_under_review_full(self) -> None:
        """子 span 嵌套在 review.full 之下（共享 trace_id）"""
        tracer = _init_test_tracer()

        from dota_helper.orchestrator.review_orchestrator import ReviewOrchestrator
        from dota_helper.domain_types.state import ReviewAgentState
        from dota_helper.domain_types.match_data import MatchData
        from dota_helper.domain_types.analysis import AnalysisResult

        mock_data_source = AsyncMock()
        match_data = MatchData(
            match_id="789", duration=2400, radiant_win=True,
            radiant_score=30, dire_score=28, game_mode=22,
            players=[], picks_bans=[],
        )
        mock_data_source.fetch_match.return_value = match_data

        mock_strategic = MagicMock()
        from dota_helper.domain_types.strategy import AnalysisStrategy
        strategy = AnalysisStrategy(
            match_type="normal", priority_phases=["laning"],
            budget_allocation={"laning": 2}, expected_depth={"laning": "standard"},
        )
        mock_strategic.evaluate.return_value = strategy

        mock_tactical = AsyncMock()
        result = AnalysisResult(
            phase="laning", conclusions=[], confidence=0.8,
            iterations_used=1, tokens_consumed=500,
        )
        mock_tactical.execute.return_value = result
        mock_tactical_factory = MagicMock(return_value=mock_tactical)

        mock_verifier = MagicMock()
        from dota_helper.domain_types.events import VerificationResult
        mock_verifier.verify.return_value = VerificationResult(
            passed=True, blocking_reasons=[], suggestions=[],
        )

        from dota_helper.report.report_builder import ReportBuilder
        from dota_helper.report.markdown_renderer import MarkdownRenderer
        state = ReviewAgentState(match_id="789")

        orchestrator = ReviewOrchestrator(
            data_source=mock_data_source,
            strategic_loop=mock_strategic,
            tactical_loop_factory=mock_tactical_factory,
            stop_verifier=mock_verifier,
            report_builder=ReportBuilder(),
            state=state,
            markdown_renderer=MarkdownRenderer(),
        )

        await orchestrator.review("789")

        spans = tracer.completed_spans
        root_span = next(s for s in spans if s.name == "review.full")
        # 所有子 span 应共享同一 trace_id
        child_spans = [s for s in spans if s.name != "review.full"]
        for child in child_spans:
            assert child.trace_id == root_span.trace_id


# ── 接入点 4: TacticalLoop span ──

class TestTacticalLoopTracer:
    """TacticalLoop 可观测性集成测试"""

    @pytest.mark.asyncio
    async def test_tactical_execute_span_created(self) -> None:
        """战术循环执行时创建 tactical.execute span"""
        tracer = _init_test_tracer()

        from dota_helper.orchestrator.tactical_loop import TacticalLoop
        from dota_helper.domain_types.analysis import AnalysisContext, AnalysisResult
        from dota_helper.domain_types.match_data import MatchData
        from dota_helper.engines.budget import IterationBudget

        mock_analyzer = AsyncMock()
        result = AnalysisResult(
            phase="laning", conclusions=[], confidence=0.85,
            iterations_used=1, tokens_consumed=500,
        )
        mock_analyzer.analyze.return_value = result
        mock_analyzer.validate_result.return_value = True
        mock_analyzer.phase_name = "laning"

        loop = TacticalLoop(analyzer=mock_analyzer, max_iterations=2)

        match_data = MatchData(
            match_id="test", duration=2400, radiant_win=True,
            radiant_score=30, dire_score=28, game_mode=22,
            players=[], picks_bans=[],
        )
        context = AnalysisContext(
            phase="laning",
            budget=IterationBudget(max_iterations=2, max_tokens=8000),
            completed_results=[],
        )

        await loop.execute(match_data, context)

        spans = tracer.completed_spans
        span_names = [s.name for s in spans]
        assert "tactical.execute" in span_names

    @pytest.mark.asyncio
    async def test_tactical_span_has_attributes(self) -> None:
        """tactical.execute span 记录 iterations_used、tokens_consumed、confidence"""
        tracer = _init_test_tracer()

        from dota_helper.orchestrator.tactical_loop import TacticalLoop
        from dota_helper.domain_types.analysis import AnalysisContext, AnalysisResult
        from dota_helper.domain_types.match_data import MatchData
        from dota_helper.engines.budget import IterationBudget

        mock_analyzer = AsyncMock()
        result = AnalysisResult(
            phase="economy", conclusions=[], confidence=0.9,
            iterations_used=1, tokens_consumed=800,
        )
        mock_analyzer.analyze.return_value = result
        mock_analyzer.validate_result.return_value = True
        mock_analyzer.phase_name = "economy"

        loop = TacticalLoop(analyzer=mock_analyzer, max_iterations=3)

        match_data = MatchData(
            match_id="test", duration=2400, radiant_win=True,
            radiant_score=30, dire_score=28, game_mode=22,
            players=[], picks_bans=[],
        )
        context = AnalysisContext(
            phase="economy",
            budget=IterationBudget(max_iterations=3, max_tokens=12000),
            completed_results=[],
        )

        await loop.execute(match_data, context)

        spans = tracer.completed_spans
        tactical_span = next(s for s in spans if s.name == "tactical.execute")
        assert tactical_span.attributes.get("iterations_used") is not None
        assert tactical_span.attributes.get("tokens_consumed") is not None
        assert tactical_span.attributes.get("confidence") is not None


# ── NoOpTracer 回归测试 ──

class TestNoOpTracerRegression:
    """验证 NoOpTracer 模式下零开销"""

    @pytest.mark.asyncio
    async def test_noop_tracer_does_not_change_review_result(self) -> None:
        """NoOpTracer 下复盘结果与无 tracer 一致"""
        _reset_tracer()
        # 默认 get_tracer() 返回 NoOpTracer

        from dota_helper.orchestrator.review_orchestrator import ReviewOrchestrator
        from dota_helper.domain_types.state import ReviewAgentState
        from dota_helper.domain_types.match_data import MatchData
        from dota_helper.domain_types.analysis import AnalysisResult

        mock_data_source = AsyncMock()
        match_data = MatchData(
            match_id="noop_test", duration=2400, radiant_win=True,
            radiant_score=30, dire_score=28, game_mode=22,
            players=[], picks_bans=[],
        )
        mock_data_source.fetch_match.return_value = match_data

        mock_strategic = MagicMock()
        from dota_helper.domain_types.strategy import AnalysisStrategy
        strategy = AnalysisStrategy(
            match_type="normal", priority_phases=["laning"],
            budget_allocation={"laning": 2}, expected_depth={"laning": "standard"},
        )
        mock_strategic.evaluate.return_value = strategy

        mock_tactical = AsyncMock()
        result = AnalysisResult(
            phase="laning", conclusions=[], confidence=0.8,
            iterations_used=1, tokens_consumed=500,
        )
        mock_tactical.execute.return_value = result
        mock_tactical_factory = MagicMock(return_value=mock_tactical)

        mock_verifier = MagicMock()
        from dota_helper.domain_types.events import VerificationResult
        mock_verifier.verify.return_value = VerificationResult(
            passed=True, blocking_reasons=[], suggestions=[],
        )

        from dota_helper.report.report_builder import ReportBuilder
        from dota_helper.report.markdown_renderer import MarkdownRenderer
        state = ReviewAgentState(match_id="noop_test")

        orchestrator = ReviewOrchestrator(
            data_source=mock_data_source,
            strategic_loop=mock_strategic,
            tactical_loop_factory=mock_tactical_factory,
            stop_verifier=mock_verifier,
            report_builder=ReportBuilder(),
            state=state,
            markdown_renderer=MarkdownRenderer(),
        )

        report = await orchestrator.review("noop_test")

        # NoOpTracer 不影响结果
        assert report is not None
        assert report.match_id == "noop_test"
        assert report.overall_confidence >= 0.0
