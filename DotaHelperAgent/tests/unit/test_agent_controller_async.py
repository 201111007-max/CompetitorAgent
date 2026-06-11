# tests/unit/test_agent_controller_async.py
import pytest
import asyncio
from unittest.mock import Mock, MagicMock, patch
from core.agent_controller import AgentController, AgentThought
from tools.base import ToolResult, ToolStatus


@pytest.fixture
def mock_tool_registry():
    """创建模拟的工具注册表"""
    registry = Mock()

    # 模拟工具执行
    def mock_execute(tool_name, **kwargs):
        return ToolResult(
            tool_name=tool_name,
            status=ToolStatus.SUCCESS,
            data={"result": f"success_{tool_name}"}
        )

    registry.execute = mock_execute
    registry.get = Mock(return_value=Mock())
    return registry


@pytest.fixture
def mock_llm_client():
    """创建模拟的 LLM 客户端"""
    client = Mock()
    client.generate = Mock(return_value="test response")
    return client


@pytest.fixture
def agent_controller(mock_tool_registry, mock_llm_client):
    """创建 AgentController 实例"""
    return AgentController(
        tool_registry=mock_tool_registry,
        llm_client=mock_llm_client,
        max_turns=3
    )


def test_agent_controller_initialization(agent_controller):
    """测试 AgentController 初始化"""
    assert agent_controller is not None
    assert agent_controller.parallel_config is not None
    assert agent_controller.dependency_analyzer is not None
    assert agent_controller.parallel_executor is not None


def test_execute_async_with_parallel_tools(agent_controller):
    """测试异步执行（并行工具）"""
    thought = AgentThought(
        query="test query",
        context={
            "planned_tools": ["tool_1", "tool_2"],
            "tool_params": {
                "tool_1": {"param1": "value1"},
                "tool_2": {"param2": "value2"}
            }
        }
    )

    # 运行异步执行
    asyncio.run(agent_controller._execute_async(thought))

    # 验证工具被执行
    assert len(thought.actions_taken) == 2
    assert len(thought.observations) == 2


def test_execute_async_with_dependent_tools(agent_controller):
    """测试异步执行（有依赖工具）"""
    thought = AgentThought(
        query="test query",
        context={
            "planned_tools": ["tool_1", "tool_2"],
            "tool_params": {
                "tool_1": {"param1": "value1"},
                "tool_2": {"param2": "from_tool_1"}  # 依赖 tool_1
            }
        }
    )

    # 运行异步执行
    asyncio.run(agent_controller._execute_async(thought))

    # 验证工具被执行（可能因为 _has_sufficient_data 提前完成）
    assert len(thought.actions_taken) >= 1
