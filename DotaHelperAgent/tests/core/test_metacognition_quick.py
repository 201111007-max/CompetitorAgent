"""快速测试元认知模块"""
import sys
from pathlib import Path

project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

print("=" * 60)
print("测试元认知模块")
print("=" * 60)

print("\n1. 测试接口导入...")
try:
    from core.metacognition.interfaces import (
        IKnowledgeBoundary,
        IConfidenceCalculator,
        IClarificationGenerator,
        IMetacognitionEvaluator,
        KnowledgeAssessment,
        ClarificationRequest,
        ConfidenceLevel
    )
    print("   ✓ 接口导入成功")
except Exception as e:
    print(f"   ✗ 接口导入失败: {e}")
    sys.exit(1)

print("\n2. 测试规则驱动实现导入...")
try:
    from core.metacognition.rule_based import (
        RuleBasedKnowledgeBoundary,
        WeightedConfidenceCalculator,
        RuleBasedClarificationGenerator,
        RuleBasedMetacognitionEvaluator
    )
    print("   ✓ 规则驱动实现导入成功")
except Exception as e:
    print(f"   ✗ 规则驱动实现导入失败: {e}")
    sys.exit(1)

print("\n3. 测试工厂类导入...")
try:
    from core.metacognition.factory import MetacognitionFactory
    print("   ✓ 工厂类导入成功")
except Exception as e:
    print(f"   ✗ 工厂类导入失败: {e}")
    sys.exit(1)

print("\n4. 测试 KnowledgeAssessment 数据类...")
try:
    assessment = KnowledgeAssessment(
        confidence_score=0.85,
        confidence_level=ConfidenceLevel.HIGH,
        knowledge_coverage=0.9,
        data_quality_score=0.8,
        reasoning="数据覆盖充分"
    )
    assert assessment.confidence_score == 0.85
    assert assessment.confidence_level == ConfidenceLevel.HIGH
    
    result_dict = assessment.to_dict()
    assert result_dict["confidence_score"] == 0.85
    assert result_dict["confidence_level"] == "high"
    
    assessment2 = KnowledgeAssessment.from_dict(result_dict)
    assert assessment2.confidence_score == 0.85
    print("   ✓ KnowledgeAssessment 测试通过")
except Exception as e:
    print(f"   ✗ KnowledgeAssessment 测试失败: {e}")
    sys.exit(1)

print("\n5. 测试 RuleBasedKnowledgeBoundary...")
try:
    boundary = RuleBasedKnowledgeBoundary(
        tool_registry=None,
        memory=None,
        api_client=None
    )
    
    assessment = boundary.assess(
        query="克制敌方的英雄推荐",
        context={
            "our_heroes": ["Anti-Mage"],
            "enemy_heroes": ["Pudge"],
            "data_sources": ["opendota"]
        }
    )
    
    assert isinstance(assessment, KnowledgeAssessment)
    assert 0.0 <= assessment.confidence_score <= 1.0
    print(f"   ✓ RuleBasedKnowledgeBoundary 测试通过 (置信度: {assessment.confidence_score:.2f})")
except Exception as e:
    print(f"   ✗ RuleBasedKnowledgeBoundary 测试失败: {e}")
    sys.exit(1)

print("\n6. 测试 WeightedConfidenceCalculator...")
try:
    calculator = WeightedConfidenceCalculator()
    
    factors = {
        "knowledge_coverage": 0.8,
        "data_quality": 0.7,
        "tool_match": 0.9,
        "memory_relevance": 0.6
    }
    
    result = calculator.calculate(factors)
    assert 0.0 <= result <= 1.0
    
    level = calculator.get_level(result)
    assert level in ConfidenceLevel
    print(f"   ✓ WeightedConfidenceCalculator 测试通过 (结果: {result:.3f}, 等级: {level.value})")
except Exception as e:
    print(f"   ✗ WeightedConfidenceCalculator 测试失败: {e}")
    sys.exit(1)

print("\n7. 测试 RuleBasedClarificationGenerator...")
try:
    generator = RuleBasedClarificationGenerator()
    
    assessment = KnowledgeAssessment(
        confidence_score=0.3,
        confidence_level=ConfidenceLevel.LOW,
        knowledge_coverage=0.3,
        data_quality_score=0.4,
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
    print(f"   ✓ RuleBasedClarificationGenerator 测试通过 (类型: {request.type})")
except Exception as e:
    print(f"   ✗ RuleBasedClarificationGenerator 测试失败: {e}")
    sys.exit(1)

print("\n8. 测试 RuleBasedMetacognitionEvaluator...")
try:
    boundary = RuleBasedKnowledgeBoundary()
    calculator = WeightedConfidenceCalculator()
    generator = RuleBasedClarificationGenerator()
    
    evaluator = RuleBasedMetacognitionEvaluator(
        knowledge_boundary=boundary,
        confidence_calculator=calculator,
        clarification_generator=generator,
        clarification_threshold=ConfidenceLevel.LOW
    )
    
    assessment = evaluator.assess_before_execution(
        query="出装建议",
        context={"our_heroes": ["Anti-Mage"]}
    )
    
    assert isinstance(assessment, KnowledgeAssessment)
    
    should_clarify = evaluator.should_request_clarification(assessment)
    print(f"   ✓ RuleBasedMetacognitionEvaluator 测试通过 (需要澄清: {should_clarify})")
except Exception as e:
    print(f"   ✗ RuleBasedMetacognitionEvaluator 测试失败: {e}")
    sys.exit(1)

print("\n9. 测试 MetacognitionFactory...")
try:
    config = {"type": "rule_based"}
    
    evaluator = MetacognitionFactory.create_evaluator(
        config=config,
        tool_registry=None,
        memory=None,
        api_client=None,
        llm_client=None
    )
    
    assert isinstance(evaluator, IMetacognitionEvaluator)
    print("   ✓ MetacognitionFactory 测试通过")
except Exception as e:
    print(f"   ✗ MetacognitionFactory 测试失败: {e}")
    sys.exit(1)

print("\n10. 测试 AgentController 集成...")
try:
    from unittest.mock import Mock, patch
    
    with patch('core.agent_controller.ToolRegistry') as mock_registry, \
         patch('core.agent_controller.LLMToolSelector') as mock_selector, \
         patch('core.agent_controller.ContextAugmenter') as mock_augmenter, \
         patch('core.agent_controller.GoalPlanner') as mock_planner:
        
        from core.agent_controller import AgentController
        
        mock_registry_instance = Mock()
        mock_registry.return_value = mock_registry_instance
        
        mock_llm = Mock()
        
        controller = AgentController(
            tool_registry=mock_registry_instance,
            llm_client=mock_llm,
            metacognition_config={"type": "rule_based"}
        )
        
        assert controller.enable_metacognition is True
        assert controller.metacognition is not None
        print("   ✓ AgentController 集成测试通过")
except Exception as e:
    print(f"   ✗ AgentController 集成测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("所有测试通过！✓")
print("=" * 60)
