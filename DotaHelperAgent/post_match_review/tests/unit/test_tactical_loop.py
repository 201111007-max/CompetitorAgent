"""战术循环单元测试"""
import pytest
from unittest.mock import AsyncMock, Mock

from post_match_review.orchestrator.tactical_loop import TacticalLoop
from post_match_review.types.analysis import (
    AnalysisContext,
    AnalysisResult,
    Conclusion,
)
from post_match_review.types.match_data import MatchData, PlayerData
from post_match_review.types.enums import BudgetDecision
from post_match_review.engines.budget import IterationBudget


class TestTacticalLoop:
    """测试战术循环"""

    def _create_match_data(self) -> MatchData:
        """创建测试用比赛数据"""
        return MatchData(
            match_id="8893253595",
            duration=1800,
            radiant_win=True,
            radiant_score=35,
            dire_score=20,
            game_mode=22,
            players=[
                PlayerData(
                    account_id="100000000",
                    hero_id=8,
                    hero_name="Juggernaut",
                    kills=10,
                    deaths=2,
                    assists=15,
                    last_hits=250,
                    denies=15,
                    gpm=650,
                    xpm=700,
                    hero_damage=25000,
                    tower_damage=8000,
                    is_radiant=True,
                    is_user=True,
                )
            ],
            picks_bans=[],
        )

    def _create_mock_analyzer(
        self,
        confidence: float = 0.8,
        conclusions_count: int = 3,
        validate_result: bool = True,
    ) -> Mock:
        """创建模拟分析器"""
        analyzer = Mock()
        analyzer.phase_name = "laning"

        conclusions = [
            Conclusion(
                title=f"结论 {i+1}",
                content=f"内容 {i+1}",
                evidence=[f"证据 {i+1}"],
                has_evidence=True,
                impact="medium",
            )
            for i in range(conclusions_count)
        ]

        result = AnalysisResult(
            phase="laning",
            conclusions=conclusions,
            confidence=confidence,
            iterations_used=1,
            tokens_consumed=100,
            analysis_text="分析文本",
        )

        analyzer.analyze = AsyncMock(return_value=result)
        analyzer.validate_result = Mock(return_value=validate_result)

        return analyzer

    @pytest.mark.asyncio
    async def test_execute_single_iteration_success(self) -> None:
        """测试单次迭代成功"""
        analyzer = self._create_mock_analyzer(confidence=0.8)
        budget = IterationBudget(max_iterations=3, max_tokens=10000)
        context = AnalysisContext(phase="laning", budget=budget)
        match_data = self._create_match_data()

        loop = TacticalLoop(analyzer=analyzer, max_iterations=3)
        result = await loop.execute(match_data, context)

        assert result.phase == "laning"
        assert result.confidence == 0.8
        assert len(result.conclusions) == 3
        assert result.iterations_used == 1
        analyzer.analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_multiple_iterations_until_quality_met(self) -> None:
        """测试多次迭代直到质量达标"""
        analyzer = Mock()
        analyzer.phase_name = "laning"

        # 第一次返回低置信度，第二次返回高置信度
        low_result = AnalysisResult(
            phase="laning",
            conclusions=[],
            confidence=0.4,
            iterations_used=1,
            tokens_consumed=100,
        )
        high_result = AnalysisResult(
            phase="laning",
            conclusions=[
                Conclusion(
                    title="结论",
                    content="内容",
                    evidence=["证据"],
                    has_evidence=True,
                )
            ],
            confidence=0.8,
            iterations_used=1,
            tokens_consumed=100,
        )

        analyzer.analyze = AsyncMock(side_effect=[low_result, high_result])
        analyzer.validate_result = Mock(side_effect=[False, True])

        budget = IterationBudget(max_iterations=5, max_tokens=10000)
        context = AnalysisContext(phase="laning", budget=budget)
        match_data = self._create_match_data()

        loop = TacticalLoop(analyzer=analyzer, max_iterations=5)
        result = await loop.execute(match_data, context)

        assert result.confidence == 0.8
        assert result.iterations_used == 2
        assert analyzer.analyze.call_count == 2

    @pytest.mark.asyncio
    async def test_execute_budget_exhausted(self) -> None:
        """测试预算耗尽"""
        analyzer = self._create_mock_analyzer(confidence=0.4, validate_result=False)
        budget = IterationBudget(max_iterations=2, max_tokens=10000)
        context = AnalysisContext(phase="laning", budget=budget)
        match_data = self._create_match_data()

        loop = TacticalLoop(analyzer=analyzer, max_iterations=5)
        result = await loop.execute(match_data, context)

        # 应该只迭代 2 次（预算限制）
        assert result.iterations_used == 2
        assert analyzer.analyze.call_count == 2

    @pytest.mark.asyncio
    async def test_execute_refund_on_quality_met(self) -> None:
        """测试质量达标时退还预算"""
        analyzer = self._create_mock_analyzer(confidence=0.8)
        budget = IterationBudget(max_iterations=5, max_tokens=10000)
        context = AnalysisContext(phase="laning", budget=budget)
        match_data = self._create_match_data()

        initial_remaining = budget.remaining_iterations

        loop = TacticalLoop(analyzer=analyzer, max_iterations=5)
        result = await loop.execute(match_data, context)

        # 质量达标后应该退还配额
        # 迭代 1 次，消费 1 次，退还 1 次，净消耗 0
        assert result.iterations_used == 1
        assert budget.remaining_iterations == initial_remaining

    @pytest.mark.asyncio
    async def test_execute_generates_feedback_on_low_quality(self) -> None:
        """测试低质量时生成反馈"""
        analyzer = Mock()
        analyzer.phase_name = "laning"

        low_result = AnalysisResult(
            phase="laning",
            conclusions=[],
            confidence=0.3,
            iterations_used=1,
            tokens_consumed=100,
        )
        high_result = AnalysisResult(
            phase="laning",
            conclusions=[
                Conclusion(
                    title="结论",
                    content="内容",
                    evidence=["证据"],
                    has_evidence=True,
                )
            ],
            confidence=0.8,
            iterations_used=1,
            tokens_consumed=100,
        )

        analyzer.analyze = AsyncMock(side_effect=[low_result, high_result])
        analyzer.validate_result = Mock(side_effect=[False, True])

        budget = IterationBudget(max_iterations=5, max_tokens=10000)
        context = AnalysisContext(phase="laning", budget=budget)
        match_data = self._create_match_data()

        loop = TacticalLoop(analyzer=analyzer, max_iterations=5)
        await loop.execute(match_data, context)

        # 验证第二次调用时 context 包含了反馈
        assert context.iteration_feedback is not None
        assert len(context.iteration_feedback) > 0

    @pytest.mark.asyncio
    async def test_execute_no_result_returns_empty(self) -> None:
        """测试无结果时返回空结果"""
        analyzer = Mock()
        analyzer.phase_name = "laning"

        # 预算立即耗尽
        budget = IterationBudget(max_iterations=0, max_tokens=10000)
        context = AnalysisContext(phase="laning", budget=budget)
        match_data = self._create_match_data()

        loop = TacticalLoop(analyzer=analyzer, max_iterations=3)
        result = await loop.execute(match_data, context)

        assert result.phase == "laning"
        assert result.confidence == 0.0
        assert result.iterations_used == 0
        analyzer.analyze.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_tracks_tokens_consumed(self) -> None:
        """测试追踪 Token 消耗"""
        analyzer = Mock()
        analyzer.phase_name = "laning"

        result1 = AnalysisResult(
            phase="laning",
            conclusions=[],
            confidence=0.4,
            iterations_used=1,
            tokens_consumed=150,
        )
        result2 = AnalysisResult(
            phase="laning",
            conclusions=[
                Conclusion(
                    title="结论",
                    content="内容",
                    evidence=["证据"],
                    has_evidence=True,
                )
            ],
            confidence=0.8,
            iterations_used=1,
            tokens_consumed=200,
        )

        analyzer.analyze = AsyncMock(side_effect=[result1, result2])
        analyzer.validate_result = Mock(side_effect=[False, True])

        budget = IterationBudget(max_iterations=5, max_tokens=10000)
        context = AnalysisContext(phase="laning", budget=budget)
        match_data = self._create_match_data()

        loop = TacticalLoop(analyzer=analyzer, max_iterations=5)
        result = await loop.execute(match_data, context)

        assert result.tokens_consumed == 350  # 150 + 200
