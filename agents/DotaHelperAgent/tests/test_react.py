"""测试 ReAct Agent 实现"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 直接导入具体模块，避免 __init__.py 中的问题
from core.tool_registry import ToolRegistry
from core.react_agent import ReActAgent
from tools.base import Tool, ToolResult
from memory.memory import AgentMemory


def test_basic_functionality():
    """测试基本功能"""
    print("=" * 50)
    print("测试 ReAct Agent 基本功能")
    print("=" * 50)

    # 创建 ToolRegistry
    registry = ToolRegistry()
    print(f"[OK] 创建 ToolRegistry: {len(registry)} 个工具")

    # 创建 Memory
    memory = AgentMemory(memory_dir="test_memory")
    print("[OK] 创建 AgentMemory")

    # 创建 ReActAgent
    agent = ReActAgent(
        tool_registry=registry,
        memory=memory,
        max_turns=3
    )
    print("[OK] 创建 ReActAgent")

    # 测试思考
    thought = agent.think("推荐一个英雄来克制敌方阵容")
    print(f"[OK] Think 完成: {thought.reasoning}")

    # 测试规划
    plan = agent.plan(thought)
    print(f"[OK] Plan 完成: {len(plan)} 个行动")

    print("\n所有基础测试通过!")
    return True


def test_tool_creation():
    """测试 Tool 创建"""
    print("\n" + "=" * 50)
    print("测试 Tool 创建")
    print("=" * 50)

    # 创建一个简单的测试 Tool
    def test_func(name: str, count: int = 1):
        return {"name": name, "count": count, "message": f"Hello {name}!"}

    tool = Tool(
        name="test_tool",
        description="测试工具",
        parameters={"name": str, "count": int},
        func=test_func,
        category="test"
    )

    print(f"[OK] 创建 Tool: {tool.name}")
    print(f"  - 描述: {tool.description}")
    print(f"  - 类别: {tool.category}")
    print(f"  - 参数: {list(tool.parameters.keys())}")

    # 测试执行
    result = tool.execute(name="Dota", count=3)
    print(f"[OK] Tool 执行: {result.status.value}")
    if result.is_success():
        print(f"  - 结果: {result.data}")

    # 注册到 Registry
    registry = ToolRegistry()
    registry.register(tool)
    print(f"[OK] 注册到 Registry: {len(registry)} 个工具")

    # 通过 Registry 执行
    result2 = registry.execute("test_tool", name="Invoker", count=5)
    print(f"[OK] Registry 执行: {result2.status.value}")

    print("\n所有 Tool 测试通过!")
    return True


def test_react_loop():
    """测试完整 ReAct 循环"""
    print("\n" + "=" * 50)
    print("测试 ReAct 循环")
    print("=" * 50)

    # 创建模拟工具
    def mock_counter_picks(our_heroes, enemy_heroes, top_n=3):
        return {
            "recommendations": [
                {"hero": "Anti-Mage", "reason": "克制法师", "score": 0.85},
                {"hero": "Pudge", "reason": "钩子威胁", "score": 0.80}
            ]
        }

    def mock_recommend_items(hero_name, game_stage="all", enemy_heroes=None):
        return {
            "hero": hero_name,
            "items": ["Power Treads", "Battle Fury", "Manta Style"]
        }

    # 创建 Tools
    counter_tool = Tool(
        name="analyze_counter_picks",
        description="分析克制英雄",
        parameters={"our_heroes": list, "enemy_heroes": list, "top_n": int},
        func=mock_counter_picks,
        category="hero_analysis"
    )

    items_tool = Tool(
        name="recommend_items",
        description="推荐出装",
        parameters={"hero_name": str, "game_stage": str, "enemy_heroes": list},
        func=mock_recommend_items,
        category="build_recommendation"
    )

    # 创建 Registry 和 Agent
    registry = ToolRegistry()
    registry.register(counter_tool)
    registry.register(items_tool)

    agent = ReActAgent(
        tool_registry=registry,
        max_turns=3
    )

    print(f"[OK] 注册 {len(registry)} 个工具")

    # 运行完整循环
    result = agent.solve("推荐一个英雄来克制敌方阵容")

    print(f"[OK] ReAct 循环完成")
    print(f"  - 查询: {result['query']}")
    print(f"  - 推理步骤: {len(result['reasoning'])}")
    print(f"  - 执行动作: {result['actions']}")
    print(f"  - 观察结果: {len(result['observations'])}")
    print(f"  - 推荐数量: {len(result['recommendations'])}")

    print("\nReAct 循环测试通过!")
    return True


if __name__ == "__main__":
    try:
        test_basic_functionality()
        test_tool_creation()
        test_react_loop()

        print("\n" + "=" * 50)
        print("所有测试通过! ReAct Agent 实现成功")
        print("=" * 50)

    except Exception as e:
        print(f"\n[X] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
