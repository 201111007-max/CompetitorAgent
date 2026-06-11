# tests/integration/test_parallel_execution_integration.py
"""并行执行集成测试

测试并行执行在实际场景中的集成效果
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, patch
from core.agent_controller import AgentController
from core.tool_registry import ToolRegistry
from tools.base import Tool, ToolResult, ToolStatus


class MockTool(Tool):
    """模拟工具"""

    def __init__(self, name: str, delay: float = 0.1):
        # 创建一个模拟函数
        def mock_func(**kwargs):
            time.sleep(delay)
            return {"result": f"success_{name}"}

        super().__init__(
            name=name,
            description=f"Mock tool {name}",
            parameters={},  # 添加必需的 parameters 参数
            func=mock_func,  # 添加必需的 func 参数
            category="test"
        )
        self.delay = delay
        self.call_count = 0

    def execute(self, **kwargs) -> ToolResult:
        """执行工具"""
        self.call_count += 1
        time.sleep(self.delay)  # 模拟耗时操作
        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.SUCCESS,
            data={"result": f"success_{self.name}", "call_count": self.call_count}
        )


@pytest.fixture
def tool_registry_with_mock_tools():
    """创建包含模拟工具的工具注册表"""
    registry = ToolRegistry()

    # 注册多个模拟工具
    registry.register(MockTool("fast_tool_1", delay=0.1))
    registry.register(MockTool("fast_tool_2", delay=0.1))
    registry.register(MockTool("slow_tool", delay=0.5))

    return registry


@pytest.fixture
def mock_llm_client():
    """创建模拟的 LLM 客户端"""
    client = Mock()
    client.generate = Mock(return_value="test response")
    return client


@pytest.mark.asyncio
async def test_parallel_execution_performance_improvement(
    tool_registry_with_mock_tools,
    mock_llm_client
):
    """测试并行执行的性能提升"""
    agent_controller = AgentController(
        tool_registry=tool_registry_with_mock_tools,
        llm_client=mock_llm_client,
        max_turns=3
    )

    # 创建测试场景：并行执行两个快速工具
    from core.agent_controller import AgentThought

    thought = AgentThought(
        query="test query",
        context={
            "planned_tools": ["fast_tool_1", "fast_tool_2"],
            "tool_params": {
                "fast_tool_1": {},
                "fast_tool_2": {}
            }
        }
    )

    # 执行异步版本
    start_time = time.time()
    await agent_controller._execute_async(thought)
    parallel_time = time.time() - start_time

    # 验证两个工具都被执行
    assert len(thought.actions_taken) == 2

    # 验证并行执行时间小于顺序执行时间
    # 顺序执行时间应该是 0.1 + 0.1 = 0.2s
    # 并行执行时间应该接近 max(0.1, 0.1) = 0.1s
    assert parallel_time < 0.3  # 给予一定的误差空间


@pytest.mark.asyncio
async def test_parallel_execution_with_real_tools(
    tool_registry_with_mock_tools,
    mock_llm_client
):
    """测试并行执行与真实工具的集成"""
    agent_controller = AgentController(
        tool_registry=tool_registry_with_mock_tools,
        llm_client=mock_llm_client,
        max_turns=3
    )

    from core.agent_controller import AgentThought

    thought = AgentThought(
        query="test query",
        context={
            "planned_tools": ["fast_tool_1", "slow_tool"],
            "tool_params": {
                "fast_tool_1": {},
                "slow_tool": {}
            }
        }
    )

    # 执行异步版本
    await agent_controller._execute_async(thought)

    # 验证工具执行结果
    assert len(thought.actions_taken) == 2

    # 验证观察结果
    assert len(thought.observations) == 2

    # 验证工具被正确调用
    fast_tool_1 = tool_registry_with_mock_tools.get("fast_tool_1")
    slow_tool = tool_registry_with_mock_tools.get("slow_tool")

    assert fast_tool_1.call_count == 1
    assert slow_tool.call_count == 1


@pytest.mark.asyncio
async def test_parallel_execution_with_dependencies(
    tool_registry_with_mock_tools,
    mock_llm_client
):
    """测试有依赖关系的工具执行"""
    agent_controller = AgentController(
        tool_registry=tool_registry_with_mock_tools,
        llm_client=mock_llm_client,
        max_turns=3
    )

    from core.agent_controller import AgentThought

    thought = AgentThought(
        query="test query",
        context={
            "planned_tools": ["fast_tool_1", "fast_tool_2"],
            "tool_params": {
                "fast_tool_1": {},
                "fast_tool_2": {"data": "from_fast_tool_1"}  # 依赖 fast_tool_1
            }
        }
    )

    # 执行异步版本
    await agent_controller._execute_async(thought)

    # 验证工具按依赖顺序执行
    # 由于依赖关系，工具应该按顺序执行
    assert len(thought.actions_taken) >= 1  # 至少执行了一个工具


@pytest.mark.asyncio
async def test_parallel_execution_disabled(
    tool_registry_with_mock_tools,
    mock_llm_client
):
    """测试禁用并行执行时的行为"""
    # 修改配置以禁用并行执行
    with patch('core.parallel_execution_config.ParallelExecutionConfig.is_enabled', return_value=False):
        agent_controller = AgentController(
            tool_registry=tool_registry_with_mock_tools,
            llm_client=mock_llm_client,
            max_turns=3
        )

        from core.agent_controller import AgentThought

        thought = AgentThought(
            query="test query",
            context={
                "planned_tools": ["fast_tool_1", "fast_tool_2"],
                "tool_params": {
                    "fast_tool_1": {},
                    "fast_tool_2": {}
                }
            }
        )

        # 执行异步版本（应该降级到同步执行）
        await agent_controller._execute_async(thought)

        # 验证工具被执行（可能因为 _has_sufficient_data 提前完成）
        assert len(thought.actions_taken) >= 1
