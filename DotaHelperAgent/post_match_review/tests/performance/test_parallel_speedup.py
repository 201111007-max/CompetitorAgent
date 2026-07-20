"""性能基准测试：并行 vs 串行执行速度对比"""
import asyncio
import time
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

from post_match_review.interfaces.analyzer import IReviewAnalyzer
from post_match_review.parallel.parallel_runner import ParallelRunner
from post_match_review.parallel.subagent import SubAgent
from post_match_review.types.analysis import AnalysisContext, AnalysisResult, Conclusion
from post_match_review.types.match_data import MatchData


class MockAnalyzer:
    """模拟分析器，固定延迟 500ms"""

    def __init__(self, phase_name: str, delay: float = 0.5) -> None:
        self._phase_name = phase_name
        self._delay = delay

    @property
    def phase_name(self) -> str:
        return self._phase_name

    async def analyze(
        self,
        match_data: MatchData,
        context: AnalysisContext,
    ) -> AnalysisResult:
        """模拟分析，固定延迟"""
        await asyncio.sleep(self._delay)
        return AnalysisResult(
            phase=self._phase_name,
            conclusions=[
                Conclusion(
                    title=f"测试结论-{self._phase_name}",
                    content="测试内容",
                    evidence=["测试证据"],
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
async def test_serial_execution_baseline() -> None:
    """串行执行基准测试：5 个阶段，每个 500ms，预期 ~2500ms"""
    phases = ["laning", "teamfight", "economy", "decisions", "vision"]
    match_data = create_mock_match_data()

    start_time = time.time()

    # 串行执行
    results: List[AnalysisResult] = []
    for phase in phases:
        analyzer = MockAnalyzer(phase, delay=0.5)
        subagent = SubAgent(
            name=phase,
            analyzer=analyzer,
            budget_quota=2,
            context={},
        )
        result = await subagent.run(match_data)
        results.append(result)

    elapsed_time = time.time() - start_time

    assert len(results) == 5
    assert all(r.confidence > 0 for r in results)
    # 串行预期耗时 ~2500ms (5 * 500ms)
    assert elapsed_time >= 2.4, f"串行执行时间过短: {elapsed_time:.2f}s"
    assert elapsed_time < 3.0, f"串行执行时间过长: {elapsed_time:.2f}s"

    print(f"\n串行执行耗时: {elapsed_time:.2f}s")


@pytest.mark.asyncio
async def test_parallel_execution_speedup() -> None:
    """并行执行加速测试：5 个阶段，并发 4，预期 ~1500ms"""
    phases = ["laning", "teamfight", "economy", "decisions", "vision"]
    match_data = create_mock_match_data()

    # 创建子代理列表
    subagents: List[SubAgent] = []
    for phase in phases:
        analyzer = MockAnalyzer(phase, delay=0.5)
        subagent = SubAgent(
            name=phase,
            analyzer=analyzer,
            budget_quota=2,
            context={},
        )
        subagents.append(subagent)

    # 并行执行（并发数 4）
    runner = ParallelRunner(max_concurrency=4)

    start_time = time.time()
    results = await runner.run(subagents, match_data)
    elapsed_time = time.time() - start_time

    assert len(results) == 5
    assert all(r.confidence > 0 for r in results)
    # 并行预期耗时 ~1000ms (2 批次 * 500ms)
    assert elapsed_time >= 0.9, f"并行执行时间过短: {elapsed_time:.2f}s"
    assert elapsed_time < 2.0, f"并行执行时间过长: {elapsed_time:.2f}s"

    print(f"\n并行执行耗时: {elapsed_time:.2f}s")


@pytest.mark.asyncio
async def test_parallel_vs_serial_speedup_ratio() -> None:
    """验证并行相较串行加速比 > 30%"""
    phases = ["laning", "teamfight", "economy", "decisions", "vision"]
    match_data = create_mock_match_data()

    # 串行执行
    serial_start = time.time()
    for phase in phases:
        analyzer = MockAnalyzer(phase, delay=0.5)
        subagent = SubAgent(
            name=phase,
            analyzer=analyzer,
            budget_quota=2,
            context={},
        )
        await subagent.run(match_data)
    serial_time = time.time() - serial_start

    # 并行执行
    subagents: List[SubAgent] = []
    for phase in phases:
        analyzer = MockAnalyzer(phase, delay=0.5)
        subagent = SubAgent(
            name=phase,
            analyzer=analyzer,
            budget_quota=2,
            context={},
        )
        subagents.append(subagent)

    runner = ParallelRunner(max_concurrency=4)
    parallel_start = time.time()
    await runner.run(subagents, match_data)
    parallel_time = time.time() - parallel_start

    # 计算加速比
    speedup = (serial_time - parallel_time) / serial_time * 100

    print(f"\n串行耗时: {serial_time:.2f}s")
    print(f"并行耗时: {parallel_time:.2f}s")
    print(f"加速比: {speedup:.1f}%")

    # 验证加速比 > 30%
    assert speedup > 30, f"加速比不足: {speedup:.1f}% < 30%"


@pytest.mark.asyncio
async def test_parallel_concurrency_control() -> None:
    """测试并发控制：验证最大并发数限制"""
    phases = ["phase_1", "phase_2", "phase_3", "phase_4", "phase_5", "phase_6"]
    match_data = create_mock_match_data()

    # 创建子代理
    subagents: List[SubAgent] = []
    for phase in phases:
        analyzer = MockAnalyzer(phase, delay=0.3)
        subagent = SubAgent(
            name=phase,
            analyzer=analyzer,
            budget_quota=1,
            context={},
        )
        subagents.append(subagent)

    # 并发数 2
    runner = ParallelRunner(max_concurrency=2)
    start_time = time.time()
    results = await runner.run(subagents, match_data)
    elapsed_time = time.time() - start_time

    # 6 个任务，并发 2，预期 3 批次 * 300ms = 900ms
    assert elapsed_time >= 0.85, f"执行时间过短: {elapsed_time:.2f}s"
    assert elapsed_time < 1.5, f"执行时间过长: {elapsed_time:.2f}s"
    assert len(results) == 6

    print(f"\n并发控制测试: {elapsed_time:.2f}s (预期 ~0.9s)")
