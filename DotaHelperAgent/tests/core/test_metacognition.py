"""元认知模块测试（LLM 驱动版本）

测试范围：
1. 接口定义验证
2. LLM 驱动实现
3. 工厂类
4. AgentController 集成
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch

project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.metacognition.interfaces import (
    IKnowledgeBoundary,
    IConfidenceCalculator,
    IClarificationGenerator,
    IMetacognitionEvaluator,
    KnowledgeAssessment,
    ClarificationRequest,
    ConfidenceLevel
)
from core.metacognition.rule_based import (
    WeightedConfidenceCalculator,
    RuleBasedClarificationGenerator,
    RuleBasedMetacognitionEvaluator
)
from core.metacognition.factory import MetacognitionFactory


def test_knowledge_assessment():
    """测试 KnowledgeAssessment 数据类"""
    print("  测试 KnowledgeAssessment...")
    
    assessment = KnowledgeAssessment(
        confidence_score=0.85,
        confidence_level=ConfidenceLevel.HIGH,
        knowledge_coverage=0.9,
        data_quality_score=0.8,
        reasoning="数据覆盖充分",
        limitations=["版本可能已更新"],
        data_sources=["opendota"]
    )
    
    assert assessment.confidence_score == 0.85
    assert assessment.confidence_level == ConfidenceLevel.HIGH
    assert len(assessment.limitations) == 1
    
    result = assessment.to_dict()
    assert isinstance(result, dict)
    assert result["confidence_score"] == 0.85
    assert result["confidence_level"] == "high"
    assert result["reasoning"] == "数据覆盖充分"
    
    data = {
        "confidence_score": 0.75,
        "confidence_level": "high",
        "knowledge_coverage": 0.8,
        "data_quality_score": 0.7,
        "reasoning": "从字典创建",
        "limitations": [],
        "data_sources": ["memory"]
    }
    
    assessment2 = KnowledgeAssessment.from_dict(data)
    assert assessment2.confidence_score == 0.75
    assert assessment2.confidence_level == ConfidenceLevel.HIGH
    assert assessment2.data_sources == ["memory"]
    
    print("  ✓ KnowledgeAssessment 测试通过")


def test_clarification_request():
    """测试 ClarificationRequest 数据类"""
    print("  测试 ClarificationRequest...")
    
    request = ClarificationRequest(
        type="missing_hero",
        original_query="克制谁？",
        confidence_level=ConfidenceLevel.LOW,
        missing_info=["英雄名称"],
        questions=["请问您指的是哪个英雄？"],
        suggestions=["提供英雄名称"]
    )
    
    assert request.type == "missing_hero"
    assert len(request.questions) == 1
    
    request2 = ClarificationRequest(
        type="missing_context",
        original_query="出装建议",
        confidence_level=ConfidenceLevel.MEDIUM,
        missing_info=["游戏阶段"],
        questions=["能否提供更多对局信息？"],
        suggestions=["说明游戏阶段"],
        partial_answer="一般性建议"
    )
    
    result = request2.to_dict()
    assert result["type"] == "missing_context"
    assert result["partial_answer"] == "一般性建议"
    
    print("  ✓ ClarificationRequest 测试通过")


def test_weighted_confidence_calculator():
    """测试加权置信度计算器"""
    print("  测试 WeightedConfidenceCalculator...")
    
    calculator = WeightedConfidenceCalculator()
    
    factors = {
        "knowledge_coverage": 0.8,
        "data_quality": 0.7,
        "tool_match": 0.9,
        "memory_relevance": 0.6
    }
    
    result = calculator.calculate(factors)
    assert 0.0 <= result <= 1.0
    expected = 0.8 * 0.35 + 0.7 * 0.25 + 0.9 * 0.20 + 0.6 * 0.20
    assert abs(result - expected) < 0.001
    
    factors2 = {
        "knowledge_coverage": 0.8,
        "data_quality": 0.7
    }
    weights = {
        "knowledge_coverage": 0.6,
        "data_quality": 0.4
    }
    
    result2 = calculator.calculate(factors2, weights)
    expected2 = (0.8 * 0.6 + 0.7 * 0.4) / (0.6 + 0.4)
    assert abs(result2 - expected2) < 0.001
    
    assert calculator.get_level(0.95) == ConfidenceLevel.VERY_HIGH
    assert calculator.get_level(0.8) == ConfidenceLevel.HIGH
    assert calculator.get_level(0.6) == ConfidenceLevel.MEDIUM
    assert calculator.get_level(0.4) == ConfidenceLevel.LOW
    assert calculator.get_level(0.1) == ConfidenceLevel.VERY_LOW
    
    print("  ✓ WeightedConfidenceCalculator 测试通过")


def test_rule_based_clarification_generator():
    """测试基于规则的澄清请求生成器"""
    print("  测试 RuleBasedClarificationGenerator...")
    
    generator = RuleBasedClarificationGenerator()
    
    assessment = KnowledgeAssessment(
        confidence_score=0.3,
        confidence_level=ConfidenceLevel.LOW,
        knowledge_coverage=0.3,
        data_quality_score=0.5,
        reasoning="缺少英雄信息",
        limitations=["英雄名称缺失"]
    )
    
    request = generator.generate(
        query="克制谁？",
        assessment=assessment,
        missing_info=["英雄名称"]
    )
    
    assert request.type == "missing_hero"
    assert len(request.questions) > 0
    assert len(request.suggestions) > 0
    
    assessment2 = KnowledgeAssessment(
        confidence_score=0.4,
        confidence_level=ConfidenceLevel.LOW,
        knowledge_coverage=0.4,
        data_quality_score=0.5,
        reasoning="缺少上下文",
        limitations=["游戏阶段未知"]
    )
    
    request2 = generator.generate(
        query="出装建议",
        assessment=assessment2,
        missing_info=["游戏阶段"]
    )
    
    assert request2.type == "missing_context"
    
    assert generator._determine_type(["英雄名称"], Mock()) == "missing_hero"
    assert generator._determine_type(["游戏版本"], Mock()) == "version_dependent"
    assert generator._determine_type(["意图不明"], Mock()) == "ambiguous_intent"
    assert generator._determine_type(["数据不足"], Mock()) == "insufficient_data"
    assert generator._determine_type(["其他"], Mock()) == "missing_context"
    
    print("  ✓ RuleBasedClarificationGenerator 测试通过")


def test_metacognition_factory():
    """测试元认知工厂（LLM 驱动版本）"""
    print("  测试 MetacognitionFactory...")
    
    # 测试 LLM 驱动创建
    config = {"type": "llm_based"}
    mock_llm = Mock()
    
    evaluator = MetacognitionFactory.create_evaluator(
        config=config,
        tool_registry=None,
        memory=None,
        api_client=None,
        llm_client=mock_llm
    )
    
    assert isinstance(evaluator, IMetacognitionEvaluator)
    
    # 测试默认配置（现在默认是 llm_based）
    evaluator2 = MetacognitionFactory.create_evaluator(
        config={},
        tool_registry=None,
        memory=None,
        api_client=None,
        llm_client=mock_llm
    )
    
    assert isinstance(evaluator2, IMetacognitionEvaluator)
    
    # 测试缺少 LLM 客户端时抛出异常
    try:
        MetacognitionFactory.create_evaluator(
            config={"type": "llm_based"},
            tool_registry=None,
            memory=None,
            api_client=None,
            llm_client=None
        )
        assert False, "应该抛出 ValueError"
    except ValueError as e:
        assert "需要 LLM 客户端" in str(e)
    
    # 测试未知类型抛出异常
    try:
        MetacognitionFactory.create_evaluator(
            config={"type": "unknown_type"},
            tool_registry=None,
            memory=None,
            api_client=None,
            llm_client=mock_llm
        )
        assert False, "应该抛出 ValueError"
    except ValueError as e:
        assert "未知的评估器类型" in str(e)
    
    # 测试从 YAML 创建（默认 LLM 驱动）
    evaluator3 = MetacognitionFactory.create_from_yaml(
        config_path="nonexistent.yaml",
        tool_registry=None,
        memory=None,
        api_client=None,
        llm_client=mock_llm
    )
    
    assert isinstance(evaluator3, IMetacognitionEvaluator)
    
    print("  ✓ MetacognitionFactory 测试通过")


def test_agent_controller_integration():
    """测试 AgentController 集成（LLM 驱动）"""
    print("  测试 AgentController 集成...")
    
    with patch('core.agent_controller.ToolRegistry') as mock_registry, \
         patch('core.agent_controller.LLMToolSelector') as mock_selector, \
         patch('core.agent_controller.ContextAugmenter') as mock_augmenter, \
         patch('core.agent_controller.GoalPlanner') as mock_planner:
        
        from core.agent_controller import AgentController
        
        mock_registry_instance = Mock()
        mock_registry.return_value = mock_registry_instance
        
        mock_llm = Mock()
        
        # 测试使用 LLM 驱动的元认知
        metacognition_config = {"type": "llm_based"}
        
        controller = AgentController(
            tool_registry=mock_registry_instance,
            llm_client=mock_llm,
            metacognition_config=metacognition_config
        )
        
        assert controller.enable_metacognition is True
        assert controller.metacognition is not None
        assert isinstance(controller.metacognition, IMetacognitionEvaluator)
        
        # 测试未启用元认知
        controller2 = AgentController(
            tool_registry=mock_registry_instance,
            llm_client=mock_llm
        )
        
        assert controller2.enable_metacognition is False
        assert controller2.metacognition is None
    
    print("  ✓ AgentController 集成测试通过")


def test_llm_based_knowledge_boundary():
    """测试基于 LLM 的知识边界评估"""
    print("  测试 LLMBasedKnowledgeBoundary...")
    
    from core.metacognition.llm_based import LLMBasedKnowledgeBoundary
    
    # 模拟 LLM 响应
    mock_llm = Mock()
    mock_llm.chat.return_value = {
        "choices": [{
            "message": {
                "content": """
                {
                    "coverage_score": 0.85,
                    "quality_score": 0.8,
                    "tool_match_score": 0.9,
                    "overall_score": 0.85,
                    "reasoning": "数据覆盖充分",
                    "limitations": ["版本可能已更新"],
                    "data_sources": ["opendota"]
                }
                """
            }
        }]
    }
    
    boundary = LLMBasedKnowledgeBoundary(
        llm_client=mock_llm,
        tool_registry=None
    )
    
    assessment = boundary.assess(
        query="克制敌方的英雄推荐",
        context={"our_heroes": ["Anti-Mage"], "enemy_heroes": ["Pudge"]}
    )
    
    assert isinstance(assessment, KnowledgeAssessment)
    assert 0.0 <= assessment.confidence_score <= 1.0
    mock_llm.chat.assert_called_once()
    
    # 测试 LLM 调用失败时的降级处理
    mock_llm2 = Mock()
    mock_llm2.chat.side_effect = Exception("API 错误")
    
    boundary2 = LLMBasedKnowledgeBoundary(
        llm_client=mock_llm2,
        tool_registry=None
    )
    
    assessment2 = boundary2.assess(
        query="测试查询",
        context={}
    )
    
    assert isinstance(assessment2, KnowledgeAssessment)
    assert assessment2.confidence_score == 0.5  # 默认降级值
    
    print("  ✓ LLMBasedKnowledgeBoundary 测试通过")


if __name__ == "__main__":
    print("=" * 60)
    print("测试元认知模块（LLM 驱动版本）")
    print("=" * 60)
    
    tests = [
        test_knowledge_assessment,
        test_clarification_request,
        test_weighted_confidence_calculator,
        test_rule_based_clarification_generator,
        test_metacognition_factory,
        test_agent_controller_integration,
        test_llm_based_knowledge_boundary
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ✗ {test.__name__} 失败: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
    
    if failed > 0:
        sys.exit(1)
