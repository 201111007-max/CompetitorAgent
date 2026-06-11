# tests/unit/test_parallel_executor.py
import pytest
import asyncio
from unittest.mock import Mock, MagicMock, AsyncMock
from core.parallel_executor import ParallelExecutor
from tools.base import ToolResult, ToolStatus


@pytest.fixture
def mock_tool_registry():
    """创建模拟的工具注册表"""
    registry = Mock()

    # 模拟工具执行
    def mock_execute(tool_name, **kwargs):
        if tool_name == "tool_success":
            return ToolResult(
                tool_name=tool_name,
                status=ToolStatus.SUCCESS,
                data={"result": "success"}
            )
        elif tool_name == "tool_failure":
            raise Exception("Tool execution failed")
        elif tool_name == "tool_slow":
            import time
            time.sleep(2)
            return ToolResult(
                tool_name=tool_name,
                status=ToolStatus.SUCCESS,
                data={"result": "slow"}
            )
        else:
            return ToolResult(
                tool_name=tool_name,
                status=ToolStatus.SUCCESS,
                data=kwargs
            )

    registry.execute = mock_execute
    return registry


@pytest.mark.asyncio
async def test_parallel_execution_success(mock_tool_registry):
    """测试并行执行成功"""
    executor = ParallelExecutor(
        tool_registry=mock_tool_registry,
        max_concurrency=5,
        timeout=30.0
    )

    tools = ["tool_success", "tool_success_2"]
    tool_params = {
        "tool_success": {"param1": "value1"},
        "tool_success_2": {"param2": "value2"}
    }

    results = await executor.execute_parallel(tools, tool_params)

    assert len(results) == 2
    assert "tool_success" in results
    assert "tool_success_2" in results
    assert results["tool_success"].is_success()
    assert results["tool_success_2"].is_success()


@pytest.mark.asyncio
async def test_parallel_execution_partial_failure(mock_tool_registry):
    """测试并行执行部分失败（宽松模式）"""
    executor = ParallelExecutor(
        tool_registry=mock_tool_registry,
        max_concurrency=5,
        timeout=30.0
    )

    tools = ["tool_success", "tool_failure"]
    tool_params = {
        "tool_success": {"param1": "value1"},
        "tool_failure": {"param2": "value2"}
    }

    results = await executor.execute_parallel(tools, tool_params)

    # 宽松模式：部分失败不影响其他工具
    assert len(results) == 2
    assert "tool_success" in results
    assert "tool_failure" in results
    assert results["tool_success"].is_success()
    assert isinstance(results["tool_failure"], Exception)


@pytest.mark.asyncio
async def test_parallel_execution_timeout(mock_tool_registry):
    """测试并行执行超时"""
    executor = ParallelExecutor(
        tool_registry=mock_tool_registry,
        max_concurrency=5,
        timeout=1.0  # 1秒超时
    )

    tools = ["tool_slow"]
    tool_params = {
        "tool_slow": {"param1": "value1"}
    }

    results = await executor.execute_parallel(tools, tool_params)

    # 超时应该返回异常
    assert len(results) == 1
    assert "tool_slow" in results
    assert isinstance(results["tool_slow"], Exception)


@pytest.mark.asyncio
async def test_parallel_execution_concurrency_limit(mock_tool_registry):
    """测试并发限制"""
    executor = ParallelExecutor(
        tool_registry=mock_tool_registry,
        max_concurrency=2,  # 最大并发数 2
        timeout=30.0
    )

    tools = ["tool_1", "tool_2", "tool_3", "tool_4"]
    tool_params = {tool: {"param": f"value_{tool}"} for tool in tools}

    results = await executor.execute_parallel(tools, tool_params)

    # 所有工具都应该执行完成
    assert len(results) == 4
    for tool in tools:
        assert tool in results
        assert results[tool].is_success()
