"""并行运行器单元测试"""
import asyncio
from typing import List

import pytest

from post_match_review.parallel.parallel_runner import ParallelRunner
from post_match_review.parallel.subagent import SubAgent
from post_match_review.parallel.task_queue import TaskQueue
from post_match_review.domain_types.analysis import AnalysisContext, AnalysisResult, Conclusion
from post_match_review.domain_types.match_data import MatchData


class MockAnalyzer:
    """模拟分析器"""

    def __init__(self, phase_name: str, should_fail: bool = False, delay: float = 0.1) -> None:
        self._phase_name = phase_name
        self._should_fail = should_fail
        self._delay = delay

    @property
    def phase_name(self) -> str:
        return self._phase_name

    async def analyze(
        self,
        match_data: MatchData,
        context: AnalysisContext,
    ) -> AnalysisResult:
        """模拟分析"""
        await asyncio.sleep(self._delay)

        if self._should_fail:
            raise Exception(f"分析器 {self._phase_name} 模拟失败")

        return AnalysisResult(
            phase=self._phase_name,
            conclusions=[
                Conclusion(
                    title=f"结论-{self._phase_name}",
                    content="测试内容",
                    evidence=["证据1"],
                    has_evidence=True,
                    impact="medium",
                )
            ],
            confidence=0.8,
            iterations_used=1,
            tokens_consumed=1000,
        )

    def validate_result(self, result: AnalysisResult) -> bool:
        return result.confidence >= 0.6


def create_mock_match_data() -> MatchData:
    """创建模拟比赛数据"""
    return MatchData(
        match_id="test_match_001",
        duration=2400,
        radiant_score=30,
        dire_score=28,
        radiant_win=True,
        game_mode=22,
        players=[],
        picks_bans=[],
    )


@pytest.mark.asyncio
async def test_parallel_runner_basic() -> None:
    """测试：基本并行执行功能"""
    match_data = create_mock_match_data()

    subagents = [
        SubAgent(
            name="laning",
            analyzer=MockAnalyzer("laning"),
            budget_quota=2,
            context={},
        ),
        SubAgent(
            name="teamfight",
            analyzer=MockAnalyzer("teamfight"),
            budget_quota=2,
            context={},
        ),
    ]

    runner = ParallelRunner(max_concurrency=2)
    results = await runner.run(subagents, match_data)

    assert len(results) == 2
    assert all(r.confidence > 0 for r in results)
    assert results[0].phase == "laning"
    assert results[1].phase == "teamfight"


@pytest.mark.asyncio
async def test_parallel_runner_failure_isolation() -> None:
    """测试：单个失败不影响其他任务"""
    match_data = create_mock_match_data()

    subagents = [
        SubAgent(
            name="laning",
            analyzer=MockAnalyzer("laning", should_fail=False),
            budget_quota=2,
            context={},
        ),
        SubAgent(
            name="teamfight",
            analyzer=MockAnalyzer("teamfight", should_fail=True),  # 会失败
            budget_quota=2,
            context={},
        ),
        SubAgent(
            name="economy",
            analyzer=MockAnalyzer("economy", should_fail=False),
            budget_quota=2,
            context={},
        ),
    ]

    runner = ParallelRunner(max_concurrency=3)
    results = await runner.run(subagents, match_data)

    assert len(results) == 3
    # 第一个和第三个应该成功
    assert results[0].confidence > 0
    assert results[2].confidence > 0
    # 第二个应该失败（返回空结果）
    assert results[1].confidence == 0.0
    assert "失败" in results[1].analysis_text


@pytest.mark.asyncio
async def test_parallel_runner_order_preservation() -> None:
    """测试：结果顺序与输入顺序一致"""
    match_data = create_mock_match_data()

    phases = ["laning", "teamfight", "economy", "decisions", "vision"]
    subagents = [
        SubAgent(
            name=phase,
            analyzer=MockAnalyzer(phase, delay=0.05),
            budget_quota=1,
            context={},
        )
        for phase in phases
    ]

    runner = ParallelRunner(max_concurrency=4)
    results = await runner.run(subagents, match_data)

    assert len(results) == 5
    # 验证顺序
    for i, phase in enumerate(phases):
        assert results[i].phase == phase


@pytest.mark.asyncio
async def test_parallel_runner_concurrency_limit() -> None:
    """测试：并发数限制"""
    match_data = create_mock_match_data()

    # 创建 6 个子代理
    subagents = [
        SubAgent(
            name=f"phase_{i}",
            analyzer=MockAnalyzer(f"phase_{i}", delay=0.1),
            budget_quota=1,
            context={},
        )
        for i in range(6)
    ]

    # 并发数限制为 2
    runner = ParallelRunner(max_concurrency=2)
    results = await runner.run(subagents, match_data)

    assert len(results) == 6
    assert all(r.confidence > 0 for r in results)


@pytest.mark.asyncio
async def test_parallel_runner_empty_list() -> None:
    """测试：空子代理列表"""
    match_data = create_mock_match_data()
    runner = ParallelRunner(max_concurrency=2)

    results = await runner.run([], match_data)

    assert len(results) == 0


def test_task_queue_basic_operations() -> None:
    """测试：任务队列基本操作"""
    queue = TaskQueue()

    result1 = AnalysisResult(
        phase="laning",
        conclusions=[],
        confidence=0.8,
        iterations_used=1,
        tokens_consumed=1000,
    )

    result2 = AnalysisResult(
        phase="teamfight",
        conclusions=[],
        confidence=0.7,
        iterations_used=1,
        tokens_consumed=1200,
    )

    queue.add_result(0, result1)
    queue.add_result(1, result2)

    assert queue.completed_count == 2
    assert queue.success_count == 2
    assert queue.failure_count == 0
    assert queue.is_complete(2) is True

    results = queue.get_results()
    assert len(results) == 2
    assert results[0].phase == "laning"
    assert results[1].phase == "teamfight"


def test_task_queue_with_errors() -> None:
    """测试：任务队列错误记录"""
    queue = TaskQueue()

    result1 = AnalysisResult(
        phase="laning",
        conclusions=[],
        confidence=0.8,
        iterations_used=1,
        tokens_consumed=1000,
    )

    queue.add_result(0, result1)
    queue.add_error(1, Exception("测试错误"))

    assert queue.completed_count == 2
    assert queue.success_count == 1
    assert queue.failure_count == 1

    errors = queue.get_errors()
    assert errors[0] is None
    assert errors[1] is not None
    assert "测试错误" in str(errors[1])


def test_task_queue_out_of_order() -> None:
    """测试：乱序添加结果"""
    queue = TaskQueue()

    result1 = AnalysisResult(phase="phase_0", conclusions=[], confidence=0.8)
    result2 = AnalysisResult(phase="phase_2", conclusions=[], confidence=0.7)
    result3 = AnalysisResult(phase="phase_1", conclusions=[], confidence=0.9)

    queue.add_result(0, result1)
    queue.add_result(2, result2)  # 先添加索引 2
    queue.add_result(1, result3)  # 再添加索引 1

    results = queue.get_all_results()
    assert len(results) == 3
    assert results[0].phase == "phase_0"
    assert results[1].phase == "phase_1"
    assert results[2].phase == "phase_2"


@pytest.mark.asyncio
async def test_subagent_independent_context() -> None:
    """测试：子代理独立上下文"""
    match_data = create_mock_match_data()

    subagent = SubAgent(
        name="test_phase",
        analyzer=MockAnalyzer("test_phase"),
        budget_quota=2,
        context={"depth": "standard"},
    )

    # 初始消息列表应该为空
    assert len(subagent.messages) == 0

    # 执行分析
    result = await subagent.run(match_data)

    assert result.confidence > 0
    assert result.phase == "test_phase"


@pytest.mark.asyncio
async def test_subagent_error_handling() -> None:
    """测试：子代理错误处理"""
    match_data = create_mock_match_data()

    subagent = SubAgent(
        name="failing_phase",
        analyzer=MockAnalyzer("failing_phase", should_fail=True),
        budget_quota=2,
        context={},
    )

    result = await subagent.run(match_data)

    # 应该返回空结果而不是抛出异常
    assert result.confidence == 0.0
    assert "失败" in result.analysis_text
    assert subagent.error is not None
