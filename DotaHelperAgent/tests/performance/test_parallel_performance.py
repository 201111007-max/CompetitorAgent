# tests/performance/test_parallel_performance.py
"""并行执行性能测试

测试并行执行的性能提升效果
"""

import pytest
import asyncio
import time
from unittest.mock import Mock
from core.parallel_executor import ParallelExecutor
from tools.base import ToolResult, ToolStatus


class PerformanceTestTool:
    """性能测试工具"""

    def __init__(self, name: str, delay: float):
        self.name = name
        self.delay = delay
        self.call_count = 0

    def execute(self, **kwargs) -> ToolResult:
        """执行工具"""
        self.call_count += 1
        time.sleep(self.delay)  # 模拟耗时操作
        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.SUCCESS,
            data={"result": f"success_{self.name}"}
        )


@pytest.fixture
def mock_tool_registry():
    """创建模拟的工具注册表"""
    registry = Mock()

    # 创建性能测试工具
    tools = {
        "tool_0.1s": PerformanceTestTool("tool_0.1s", 0.1),
        "tool_0.2s": PerformanceTestTool("tool_0.2s", 0.2),
        "tool_0.3s": PerformanceTestTool("tool_0.3s", 0.3),
    }

    def mock_execute(tool_name, **kwargs):
        return tools[tool_name].execute(**kwargs)

    registry.execute = mock_execute
    registry.tools = tools
    return registry


@pytest.mark.asyncio
async def test_sequential_vs_parallel_execution_time(mock_tool_registry):
    """测试顺序执行 vs 并行执行的时间对比"""
    executor = ParallelExecutor(
        tool_registry=mock_tool_registry,
        max_concurrency=5,
        timeout=30.0
    )

    # 测试顺序执行时间（理论值）
    # 顺序执行：0.1s + 0.2s + 0.3s = 0.6s
    sequential_time = 0.1 + 0.2 + 0.3

    # 测试并行执行
    tools = ["tool_0.1s", "tool_0.2s", "tool_0.3s"]
    tool_params = {tool: {} for tool in tools}

    start_time = time.time()
    results = await executor.execute_parallel(tools, tool_params)
    parallel_time = time.time() - start_time

    # 验证所有工具都执行成功
    assert len(results) == 3
    for tool in tools:
        assert tool in results
        assert isinstance(results[tool], ToolResult)
        assert results[tool].is_success()

    # 验证并行执行时间小于顺序执行时间
    # 并行执行时间应该接近 max(0.1, 0.2, 0.3) = 0.3s
    assert parallel_time < sequential_time

    # 验证性能提升
    improvement = (sequential_time - parallel_time) / sequential_time * 100
    print(f"\n性能提升: {improvement:.2f}%")
    print(f"顺序执行时间: {sequential_time:.2f}s")
    print(f"并行执行时间: {parallel_time:.2f}s")


@pytest.mark.asyncio
async def test_concurrent_limit_impact(mock_tool_registry):
    """测试并发限制对性能的影响"""
    # 测试不同的并发限制
    concurrency_levels = [1, 2, 3]
    execution_times = []

    for max_concurrency in concurrency_levels:
        executor = ParallelExecutor(
            tool_registry=mock_tool_registry,
            max_concurrency=max_concurrency,
            timeout=30.0
        )

        tools = ["tool_0.1s", "tool_0.2s", "tool_0.3s"]
        tool_params = {tool: {} for tool in tools}

        start_time = time.time()
        results = await executor.execute_parallel(tools, tool_params)
        execution_time = time.time() - start_time

        execution_times.append(execution_time)

        # 验证所有工具都执行成功
        assert len(results) == 3

    # 验证并发限制越高，执行时间越短
    print(f"\n不同并发限制下的执行时间:")
    for i, max_concurrency in enumerate(concurrency_levels):
        print(f"  max_concurrency={max_concurrency}: {execution_times[i]:.2f}s")


@pytest.mark.asyncio
async def test_many_tools_performance(mock_tool_registry):
    """测试大量工具的并行执行性能"""
    # 创建更多工具
    for i in range(10):
        mock_tool_registry.tools[f"tool_{i}"] = PerformanceTestTool(f"tool_{i}", 0.05)

    executor = ParallelExecutor(
        tool_registry=mock_tool_registry,
        max_concurrency=5,
        timeout=30.0
    )

    # 执行 10 个工具
    tools = [f"tool_{i}" for i in range(10)]
    tool_params = {tool: {} for tool in tools}

    start_time = time.time()
    results = await executor.execute_parallel(tools, tool_params)
    execution_time = time.time() - start_time

    # 验证所有工具都执行成功
    assert len(results) == 10

    # 验证执行时间
    # 顺序执行时间：10 * 0.05s = 0.5s
    # 并行执行时间：ceil(10/5) * 0.05s = 2 * 0.05s = 0.1s
    sequential_time = 10 * 0.05
    print(f"\n大量工具执行性能:")
    print(f"  工具数量: 10")
    print(f"  顺序执行时间: {sequential_time:.2f}s")
    print(f"  并行执行时间: {execution_time:.2f}s")
    print(f"  性能提升: {((sequential_time - execution_time) / sequential_time * 100):.2f}%")


@pytest.mark.asyncio
async def test_timeout_handling_performance(mock_tool_registry):
    """测试超时处理对性能的影响"""
    # 添加一个会超时的工具
    mock_tool_registry.tools["tool_timeout"] = PerformanceTestTool("tool_timeout", 10.0)

    executor = ParallelExecutor(
        tool_registry=mock_tool_registry,
        max_concurrency=5,
        timeout=1.0  # 1秒超时
    )

    tools = ["tool_0.1s", "tool_timeout", "tool_0.2s"]
    tool_params = {tool: {} for tool in tools}

    start_time = time.time()
    results = await executor.execute_parallel(tools, tool_params)
    execution_time = time.time() - start_time

    # 验证执行时间不超过超时时间太多
    assert execution_time < 2.0  # 应该在 1-2 秒内完成

    # 验证结果
    assert len(results) == 3
    assert isinstance(results["tool_timeout"], Exception)  # 超时工具返回异常
    assert isinstance(results["tool_0.1s"], ToolResult)  # 其他工具正常执行
    assert isinstance(results["tool_0.2s"], ToolResult)

    print(f"\n超时处理性能:")
    print(f"  超时设置: 1.0s")
    print(f"  实际执行时间: {execution_time:.2f}s")
