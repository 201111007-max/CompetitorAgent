"""测试新的 Agent 架构

测试 ReAct Agent 控制器、Tool Registry、Agent Tools 和 Memory 系统
"""

import sys
import os
import pytest
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent_controller import AgentController, AgentThought, AgentState
from core.tool_registry import ToolRegistry, ToolCall
from tools.base import Tool, ToolResult, ToolStatus
from tools.agent_tools import create_all_tools, create_hero_tools
from memory.memory import AgentMemory
from core.agent import DotaHelperAgent
from core.config import AgentConfig


class TestAgentController:
    """测试 Agent Controller"""

    @pytest.fixture
    def sample_tool_registry(self):
        """创建示例 Tool Registry"""
        registry = ToolRegistry()
        
        # 创建测试工具
        def test_tool_func(name: str, value: int = 10):
            return {"name": name, "value": value, "result": f"Processed {name}"}
        
        tool = Tool(
            name="test_tool",
            description="测试工具",
            parameters={"name": str, "value": int},
            func=test_tool_func,
            category="test"
        )
        
        registry.register(tool)
        return registry

    @pytest.fixture
    def sample_memory(self, tmp_path):
        """创建示例 Memory"""
        memory_dir = tmp_path / "memory"
        return AgentMemory(memory_dir=str(memory_dir))

    def test_controller_initialization(self, sample_tool_registry, sample_memory):
        """测试 Controller 初始化"""
        controller = AgentController(
            tool_registry=sample_tool_registry,
            memory=sample_memory,
            max_turns=5,
            enable_reflection=True
        )
        
        assert controller.tool_registry == sample_tool_registry
        assert controller.memory == sample_memory
        assert controller.max_turns == 5
        assert controller.enable_reflection is True

    def test_solve_basic(self, sample_tool_registry):
        """测试基本 solve 功能"""
        controller = AgentController(
            tool_registry=sample_tool_registry,
            memory=None,
            max_turns=3
        )
        
        result = controller.solve("测试查询")
        
        assert "query" in result
        assert "state" in result
        assert "reasoning" in result
        assert result["query"] == "测试查询"

    def test_thought_creation(self):
        """测试 Thought 创建"""
        thought = AgentThought(query="测试问题")
        
        assert thought.query == "测试问题"
        assert thought.state == AgentState.THINKING
        assert thought.turn_count == 0
        assert thought.state != AgentState.COMPLETE

    def test_thought_add_reasoning(self):
        """测试添加推理步骤"""
        thought = AgentThought(query="测试")
        
        thought.add_reasoning("第一步推理")
        thought.add_reasoning("第二步推理")
        
        assert len(thought.reasoning_steps) == 2
        assert "第一步推理" in thought.reasoning_steps

    def test_thought_complete(self):
        """测试完成状态"""
        thought = AgentThought(query="测试")
        answer = {"result": "测试答案"}
        
        thought.set_complete(answer)
        
        assert thought.state == AgentState.COMPLETE
        assert thought.final_answer == answer
        assert thought.end_time is not None

    def test_controller_with_context(self, sample_tool_registry):
        """测试带上下文的执行"""
        controller = AgentController(
            tool_registry=sample_tool_registry,
            memory=None
        )
        
        context = {"our_heroes": ["axe"], "enemy_heroes": ["pudge"]}
        result = controller.solve("推荐克制英雄", context)
        
        assert "context" in result
        assert result["context"]["our_heroes"] == ["axe"]


class TestToolRegistry:
    """测试 Tool Registry"""

    def test_registry_creation(self):
        """测试 Registry 创建"""
        registry = ToolRegistry()
        
        assert len(registry) == 0
        assert registry.list_tools() == []

    def test_register_tool(self):
        """测试注册工具"""
        registry = ToolRegistry()
        
        tool = Tool(
            name="test_tool",
            description="测试工具",
            parameters={"param": str},
            func=lambda param: {"result": param},
            category="test"
        )
        
        registry.register(tool)
        
        assert len(registry) == 1
        assert "test_tool" in registry
        assert registry.get("test_tool") == tool

    def test_register_duplicate_tool(self):
        """测试注册重复工具"""
        registry = ToolRegistry()
        
        tool1 = Tool(
            name="test_tool",
            description="测试工具 1",
            parameters={"param": str},
            func=lambda param: {"result": param},
            category="test"
        )
        
        tool2 = Tool(
            name="test_tool",
            description="测试工具 2",
            parameters={"param": str},
            func=lambda param: {"result": param},
            category="test"
        )
        
        registry.register(tool1)
        
        with pytest.raises(ValueError, match="already registered"):
            registry.register(tool2)

    def test_execute_tool(self):
        """测试执行工具"""
        registry = ToolRegistry()
        
        def test_func(name: str, value: int = 10):
            return {"name": name, "value": value}
        
        tool = Tool(
            name="test_tool",
            description="测试工具",
            parameters={"name": str, "value": int},
            func=test_func,
            category="test"
        )
        
        registry.register(tool)
        
        result = registry.execute("test_tool", name="Dota", value=100)
        
        assert result.is_success()
        assert result.data["name"] == "Dota"
        assert result.data["value"] == 100

    def test_execute_nonexistent_tool(self):
        """测试执行不存在的工具"""
        registry = ToolRegistry()
        
        result = registry.execute("nonexistent_tool")
        
        assert not result.is_success()
        assert "not found" in result.error

    def test_tool_stats(self):
        """测试工具统计"""
        registry = ToolRegistry()
        
        def test_func(name: str):
            return {"name": name}
        
        tool = Tool(
            name="test_tool",
            description="测试工具",
            parameters={"name": str},
            func=test_func,
            category="test"
        )
        
        registry.register(tool)
        
        # 执行多次
        registry.execute("test_tool", name="test1")
        registry.execute("test_tool", name="test2")
        
        stats = registry.get_stats("test_tool")
        
        assert stats["call_count"] == 2
        assert stats["success_count"] == 2

    def test_call_history(self):
        """测试调用历史"""
        registry = ToolRegistry()
        
        def test_func(name: str):
            return {"name": name}
        
        tool = Tool(
            name="test_tool",
            description="测试工具",
            parameters={"name": str},
            func=test_func,
            category="test"
        )
        
        registry.register(tool)
        registry.execute("test_tool", name="test")
        
        history = registry.get_call_history()
        
        assert len(history) == 1
        assert history[0].tool_name == "test_tool"


class TestAgentTools:
    """测试 Agent Tools"""

    @pytest.fixture
    def mock_hero_analyzer(self):
        """模拟英雄分析器"""
        class MockAnalyzer:
            def analyze_matchups(self, our_heroes, enemy_heroes, top_n=3):
                return {
                    "recommendations": [
                        {"hero_name": "Axe", "score": 0.9, "reasons": ["强力控制"]},
                        {"hero_name": "Sven", "score": 0.85, "reasons": ["高伤害"]}
                    ]
                }
            
            def analyze_composition(self, our_heroes, enemy_heroes):
                return {
                    "composition_score": 0.8,
                    "roles": ["carry", "support"]
                }
        
        return MockAnalyzer()

    @pytest.fixture
    def mock_client(self):
        """模拟 API 客户端"""
        class MockClient:
            def get_heroes(self):
                return [
                    {"id": 1, "name": "npc_dota_hero_axe", "localized_name": "Axe"},
                    {"id": 2, "name": "npc_dota_hero_sven", "localized_name": "Sven"}
                ]
        
        return MockClient()

    def test_create_hero_tools(self, mock_hero_analyzer, mock_client):
        """测试创建英雄工具"""
        tools = create_hero_tools(mock_hero_analyzer, mock_client)
        
        assert len(tools) >= 2
        
        tool_names = [tool.name for tool in tools]
        assert "analyze_counter_picks" in tool_names
        assert "analyze_composition" in tool_names

    def test_hero_tool_execution(self, mock_hero_analyzer, mock_client):
        """测试英雄工具执行"""
        tools = create_hero_tools(mock_hero_analyzer, mock_client)
        
        counter_tool = None
        for tool in tools:
            if tool.name == "analyze_counter_picks":
                counter_tool = tool
                break
        
        assert counter_tool is not None
        
        result = counter_tool.execute(
            our_heroes=["invoker"],
            enemy_heroes=["pudge"],
            top_n=3
        )
        
        assert result.is_success()
        assert len(result.data["recommendations"]) == 2


class TestMemoryIntegration:
    """测试 Memory 集成"""

    def test_agent_with_memory(self, tmp_path):
        """测试 Agent 带 Memory"""
        memory_dir = tmp_path / "agent_memory"
        
        agent = DotaHelperAgent(
            enable_memory=True,
            memory_dir=str(memory_dir)
        )
        
        assert agent.enable_memory is True
        assert agent.memory is not None

    def test_agent_without_memory(self):
        """测试 Agent 不带 Memory"""
        agent = DotaHelperAgent(enable_memory=False)
        
        assert agent.enable_memory is False
        assert agent.memory is None

    def test_save_query_result(self, tmp_path):
        """测试保存查询结果"""
        memory_dir = tmp_path / "query_memory"
        
        agent = DotaHelperAgent(
            enable_memory=True,
            memory_dir=str(memory_dir)
        )
        
        query = "测试查询"
        result = {"answer": "测试答案"}
        
        agent.save_query_result(query, result)
        
        # 验证记忆已保存
        stats = agent.get_memory_stats()
        assert stats["enabled"] is True

    def test_get_relevant_context(self, tmp_path):
        """测试获取相关上下文"""
        memory_dir = tmp_path / "context_memory"
        
        agent = DotaHelperAgent(
            enable_memory=True,
            memory_dir=str(memory_dir)
        )
        
        # 先保存一些数据
        agent.save_query_result("英雄推荐", {"result": "Axe"})
        agent.save_query_result("出装推荐", {"result": "Battle Fury"})
        
        # 获取相关上下文
        context = agent.get_relevant_context("英雄", limit=5)
        
        assert isinstance(context, list)


class TestReActLoop:
    """测试完整的 ReAct 循环"""

    def test_full_react_loop(self, tmp_path):
        """测试完整的 ReAct 循环"""
        # 创建 Registry
        registry = ToolRegistry()
        
        # 添加测试工具
        def counter_picks(our_heroes, enemy_heroes, top_n=3):
            return {
                "recommendations": [
                    {"hero_name": "Axe", "score": 0.9, "reasons": ["克制"]}
                ]
            }
        
        tool = Tool(
            name="analyze_counter_picks",
            description="分析克制英雄",
            parameters={"our_heroes": list, "enemy_heroes": list, "top_n": int},
            func=counter_picks,
            category="hero_analysis"
        )
        
        registry.register(tool)
        
        # 创建 Memory
        memory_dir = tmp_path / "react_memory"
        memory = AgentMemory(memory_dir=str(memory_dir))
        
        # 创建 Controller
        controller = AgentController(
            tool_registry=registry,
            memory=memory,
            max_turns=5,
            enable_reflection=True
        )
        
        # 执行查询
        context = {"our_heroes": ["invoker"], "enemy_heroes": ["pudge"]}
        result = controller.solve("推荐克制帕吉的英雄", context)
        
        # 验证结果
        assert "state" in result
        assert "reasoning" in result
        assert "actions" in result
        assert result["turn_count"] >= 1
        assert result["duration"] > 0

    def test_react_with_reflection(self):
        """测试带反思的 ReAct 循环"""
        registry = ToolRegistry()
        
        controller = AgentController(
            tool_registry=registry,
            memory=None,
            max_turns=3,
            enable_reflection=True
        )
        
        result = controller.solve("测试查询")
        
        # 验证有反思步骤
        assert "reflections" in result


class TestAgentState:
    """测试 Agent 状态管理"""

    def test_state_transitions(self):
        """测试状态转换"""
        thought = AgentThought(query="测试")
        
        # 初始状态
        assert thought.state == AgentState.THINKING
        
        # 完成状态
        thought.set_complete({"answer": "测试"})
        assert thought.state == AgentState.COMPLETE
        
        # 失败状态
        thought2 = AgentThought(query="测试")
        thought2.set_failed("错误信息")
        assert thought2.state == AgentState.FAILED

    def test_turn_counting(self):
        """测试轮次计数"""
        thought = AgentThought(query="测试")
        
        for i in range(5):
            thought.increment_turn()
        
        assert thought.turn_count == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
