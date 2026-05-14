"""策略调整集成测试

测试策略调整与 AgentController 的完整集成
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.agent_controller import AgentController, AgentThought
from core.reflection_evaluator import ReflectionResult, ReflectionAction, EvaluationDimension, QualityScore


def create_mock_dependencies():
    """创建模拟依赖"""
    mock_registry = Mock()
    mock_registry.list_tools.return_value = []
    
    mock_llm = Mock()
    mock_memory = Mock()
    mock_conversation = Mock()
    mock_tool_selector = Mock()
    
    return {
        "registry": mock_registry,
        "llm": mock_llm,
        "memory": mock_memory,
        "conversation": mock_conversation,
        "tool_selector": mock_tool_selector
    }


def create_thought_with_low_quality():
    """创建低质量结果的 thought"""
    thought = AgentThought(query="测试查询")
    thought.observations = []
    thought.actions_taken = []
    thought.reasoning_steps = ["简单推理"]
    return thought


def test_adjust_strategy_tries_more_tools():
    """测试策略调整尝试更多工具"""
    print("  测试策略调整尝试更多工具...")
    
    deps = create_mock_dependencies()
    controller = AgentController(
        tool_registry=deps["registry"],
        llm_client=deps["llm"],
        memory=deps["memory"],
        conversation_manager=deps["conversation"],
        metacognition_config={"type": "rule_based"}
    )
    
    thought = create_thought_with_low_quality()
    
    # 模拟反思评估器返回低完整性
    mock_reflection = ReflectionResult(
        action=ReflectionAction.ADJUST_STRATEGY,
        overall_score=0.4,
        dimension_scores=[
            QualityScore(EvaluationDimension.COMPLETENESS, 0.3, ["观察结果不足"]),
            QualityScore(EvaluationDimension.CONSISTENCY, 0.8, ["一致性好"]),
            QualityScore(EvaluationDimension.CREDIBILITY, 0.7, ["数据可靠"]),
            QualityScore(EvaluationDimension.RELEVANCE, 0.8, ["相关性好"]),
            QualityScore(EvaluationDimension.ACTIONABILITY, 0.6, ["可操作性一般"])
        ],
        reasoning="完整性不足",
        strategy_adjustments=["收集更多观察结果或推荐项"],
        missing_information=["可以尝试更多工具来获取信息"]
    )
    
    # Mock 反思评估器
    controller.reflection_evaluator = Mock()
    controller.reflection_evaluator.evaluate.return_value = mock_reflection
    
    # Mock 工具选择器的 select_tools 方法
    mock_tool_plan = Mock()
    mock_tool_plan.tools = []
    controller.tool_selector.select_tools = Mock(return_value=mock_tool_plan)
    
    # 执行策略调整
    controller._adjust_strategy(thought)
    
    # 验证反思评估被调用
    controller.reflection_evaluator.evaluate.assert_called_once()
    
    # 验证反思结果被记录
    assert any("反思结果" in step for step in thought.reflections)
    
    print("  ✓ 策略调整尝试更多工具测试通过")


def test_adjust_strategy_resolves_conflicts():
    """测试策略调整解决数据冲突"""
    print("  测试策略调整解决数据冲突...")
    
    deps = create_mock_dependencies()
    controller = AgentController(
        tool_registry=deps["registry"],
        llm_client=deps["llm"],
        memory=deps["memory"],
        conversation_manager=deps["conversation"],
        metacognition_config={"type": "rule_based"}
    )
    
    thought = AgentThought(query="测试查询")
    # 创建有冲突的观察结果
    thought.observations = [
        {"hero": "axe", "winrate": 0.52},
        {"hero": "axe", "winrate": 0.48}
    ]
    thought.actions_taken = []
    thought.reasoning_steps = []
    
    # 模拟低一致性
    mock_reflection = ReflectionResult(
        action=ReflectionAction.ADJUST_STRATEGY,
        overall_score=0.5,
        dimension_scores=[
            QualityScore(EvaluationDimension.CONSISTENCY, 0.4, ["数据存在矛盾"]),
            QualityScore(EvaluationDimension.COMPLETENESS, 0.8, ["完整性好"]),
            QualityScore(EvaluationDimension.CREDIBILITY, 0.7, ["数据可靠"]),
            QualityScore(EvaluationDimension.RELEVANCE, 0.8, ["相关性好"]),
            QualityScore(EvaluationDimension.ACTIONABILITY, 0.7, ["可操作性好"])
        ],
        reasoning="一致性不足",
        strategy_adjustments=["检查数据一致性，排除矛盾信息"]
    )
    
    controller.reflection_evaluator = Mock()
    controller.reflection_evaluator.evaluate.return_value = mock_reflection
    
    controller._adjust_strategy(thought)
    
    # 验证检测到冲突
    assert any("冲突" in step for step in thought.reasoning_steps)
    
    print("  ✓ 策略调整解决数据冲突测试通过")


def test_adjust_strategy_default_fallback():
    """测试策略调整降级方案"""
    print("  测试策略调整降级方案...")
    
    deps = create_mock_dependencies()
    controller = AgentController(
        tool_registry=deps["registry"],
        llm_client=deps["llm"],
        memory=deps["memory"],
        conversation_manager=deps["conversation"],
        metacognition_config={"type": "rule_based"}
    )
    
    thought = AgentThought(query="测试查询")
    thought.observations = []
    thought.actions_taken = [
        {"tool_name": "test_tool", "result": {"status": "failed"}, "parameters": {}}
    ]
    thought.reasoning_steps = []
    
    # 模拟反思评估失败
    controller.reflection_evaluator = Mock()
    controller.reflection_evaluator.evaluate.side_effect = Exception("评估失败")
    
    # Mock 工具执行
    mock_result = Mock()
    mock_result.is_success.return_value = True
    mock_result.data = {"test": "data"}
    deps["registry"].execute.return_value = mock_result
    
    controller._adjust_strategy(thought)
    
    # 验证使用了降级方案
    assert any("默认调整策略" in step for step in thought.reasoning_steps)
    
    print("  ✓ 策略调整降级方案测试通过")


def test_adjust_tool_parameters():
    """测试工具参数调整"""
    print("  测试工具参数调整...")
    
    deps = create_mock_dependencies()
    controller = AgentController(
        tool_registry=deps["registry"],
        llm_client=deps["llm"],
        memory=deps["memory"],
        conversation_manager=deps["conversation"],
        metacognition_config={"type": "rule_based"}
    )
    
    # 测试英雄分析工具参数调整
    params = controller._adjust_tool_parameters(
        "analyze_counter_picks",
        {"min_recommendations": 3}
    )
    assert params["include_alternatives"] is True
    assert params["min_recommendations"] == 5
    
    # 测试物品推荐工具参数调整
    params = controller._adjust_tool_parameters(
        "recommend_items",
        {"max_items": 5}
    )
    assert params["max_items"] == 8
    
    # 测试技能加点工具参数调整
    params = controller._adjust_tool_parameters(
        "recommend_skills",
        {}
    )
    assert params["include_explanations"] is True
    
    print("  ✓ 工具参数调整测试通过")


def test_reflection_evaluation_error_handling():
    """测试反思评估错误处理"""
    print("  测试反思评估错误处理...")
    
    deps = create_mock_dependencies()
    controller = AgentController(
        tool_registry=deps["registry"],
        llm_client=deps["llm"],
        memory=deps["memory"],
        conversation_manager=deps["conversation"],
        metacognition_config={"type": "rule_based"}
    )
    
    thought = create_thought_with_low_quality()
    
    # 模拟反思评估器抛出异常
    controller.reflection_evaluator = Mock()
    controller.reflection_evaluator.evaluate.side_effect = Exception("评估失败")
    
    # 应该降级到默认策略
    result = controller._full_reflection_evaluation(thought)
    
    assert result is None
    
    print("  ✓ 反思评估错误处理测试通过")


if __name__ == "__main__":
    print("\n=== 策略调整集成测试 ===\n")
    
    test_adjust_strategy_tries_more_tools()
    test_adjust_strategy_resolves_conflicts()
    test_adjust_strategy_default_fallback()
    test_adjust_tool_parameters()
    test_reflection_evaluation_error_handling()
    
    print("\n=== 所有测试通过 ===\n")
