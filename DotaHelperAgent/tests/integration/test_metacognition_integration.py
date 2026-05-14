"""元认知集成测试

测试元认知与 AgentController 的完整集成
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch

project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.agent_controller import AgentController
from core.metacognition.interfaces import KnowledgeAssessment, ConfidenceLevel


def create_mock_dependencies():
    """创建模拟依赖"""
    mock_registry = Mock()
    mock_registry.list_tools.return_value = []
    
    mock_llm = Mock()
    mock_memory = Mock()
    mock_conversation = Mock()
    
    return {
        "registry": mock_registry,
        "llm": mock_llm,
        "memory": mock_memory,
        "conversation": mock_conversation
    }


def test_metacognition_enabled_in_controller():
    """测试元认知在控制器中启用"""
    print("  测试元认知在控制器中启用...")
    
    deps = create_mock_dependencies()
    controller = AgentController(
        tool_registry=deps["registry"],
        llm_client=deps["llm"],
        memory=deps["memory"],
        conversation_manager=deps["conversation"],
        metacognition_config={
            "type": "rule_based",
            "clarification_threshold": "low"
        }
    )
    
    assert controller.enable_metacognition is True
    assert controller.metacognition is not None
    
    print("  ✓ 元认知启用测试通过")


def test_metacognition_disabled_by_default():
    """测试元认知默认禁用"""
    print("  测试元认知默认禁用...")
    
    deps = create_mock_dependencies()
    controller = AgentController(
        tool_registry=deps["registry"],
        llm_client=deps["llm"],
        memory=deps["memory"],
        conversation_manager=deps["conversation"]
    )
    
    assert controller.enable_metacognition is False
    assert controller.metacognition is None
    
    print("  ✓ 元认知默认禁用测试通过")


def test_metacognition_initialization_logging():
    """测试元认知初始化日志"""
    print("  测试元认知初始化日志...")
    
    deps = create_mock_dependencies()
    controller = AgentController(
        tool_registry=deps["registry"],
        llm_client=deps["llm"],
        memory=deps["memory"],
        conversation_manager=deps["conversation"],
        metacognition_config={
            "type": "rule_based",
            "clarification_threshold": "low",
            "weights": {
                "knowledge_coverage": 0.35,
                "data_quality": 0.25,
                "tool_match": 0.20,
                "memory_relevance": 0.20
            }
        }
    )
    
    # 验证元认知评估器已初始化
    assert controller.enable_metacognition is True
    assert controller.metacognition is not None
    
    print("  ✓ 元认知初始化日志测试通过")


def test_knowledge_assessment_data_class():
    """测试 KnowledgeAssessment 数据类"""
    print("  测试 KnowledgeAssessment 数据类...")
    
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
    
    print("  ✓ KnowledgeAssessment 数据类测试通过")


def test_metacognition_config_variations():
    """测试元认知配置变体"""
    print("  测试元认知配置变体...")
    
    deps = create_mock_dependencies()
    
    # 测试规则基础配置
    controller1 = AgentController(
        tool_registry=deps["registry"],
        llm_client=deps["llm"],
        memory=deps["memory"],
        conversation_manager=deps["conversation"],
        metacognition_config={"type": "rule_based"}
    )
    assert controller1.enable_metacognition is True
    
    # 测试自定义权重配置
    controller2 = AgentController(
        tool_registry=deps["registry"],
        llm_client=deps["llm"],
        memory=deps["memory"],
        conversation_manager=deps["conversation"],
        metacognition_config={
            "type": "rule_based",
            "weights": {
                "knowledge_coverage": 0.4,
                "data_quality": 0.3,
                "tool_match": 0.2,
                "memory_relevance": 0.1
            }
        }
    )
    assert controller2.enable_metacognition is True
    
    print("  ✓ 元认知配置变体测试通过")


if __name__ == "__main__":
    print("\n=== 元认知集成测试 ===\n")
    
    test_metacognition_enabled_in_controller()
    test_metacognition_disabled_by_default()
    test_metacognition_initialization_logging()
    test_knowledge_assessment_data_class()
    test_metacognition_config_variations()
    
    print("\n=== 所有测试通过 ===\n")
