"""知识融合引擎测试"""

import pytest
from knowledge.fusion_engine import KnowledgeFusionEngine, FusedKnowledge


@pytest.fixture
def fusion_engine():
    """创建知识融合引擎实例"""
    return KnowledgeFusionEngine()


def test_merge_knowledge(fusion_engine):
    """测试知识融合"""
    structured_knowledge = [
        {"hero": "幻影刺客", "item": "BKB", "source": "opendota"}
    ]

    unstructured_knowledge = [
        {"hero": "幻影刺客", "item": "蝴蝶", "source": "guide"}
    ]

    result = fusion_engine.merge(
        structured_knowledge=structured_knowledge,
        unstructured_knowledge=unstructured_knowledge,
        query="PA怎么出装？"
    )

    assert isinstance(result, FusedKnowledge)
    assert result.query == "PA怎么出装？"
    assert len(result.structured_knowledge) > 0
    assert len(result.unstructured_knowledge) > 0


def test_merge_with_conflicts(fusion_engine):
    """测试带冲突的知识融合"""
    structured_knowledge = [
        {"hero": "幻影刺客", "item": "BKB", "recommendation": "必出", "source": "guide_1"}
    ]

    unstructured_knowledge = [
        {"hero": "幻影刺客", "item": "BKB", "recommendation": "不出", "source": "guide_2"}
    ]

    result = fusion_engine.merge(
        structured_knowledge=structured_knowledge,
        unstructured_knowledge=unstructured_knowledge,
        query="PA怎么出装？"
    )

    assert len(result.conflicts) > 0


def test_calculate_overall_confidence(fusion_engine):
    """测试综合置信度计算"""
    knowledge_list = [
        {"confidence": 0.8, "source": "opendota"},
        {"confidence": 0.6, "source": "guide"}
    ]

    confidence = fusion_engine._calculate_overall_confidence(knowledge_list)
    assert 0.0 <= confidence <= 1.0


def test_merge_empty_knowledge(fusion_engine):
    """测试空知识融合"""
    result = fusion_engine.merge(
        structured_knowledge=[],
        unstructured_knowledge=[],
        query="测试查询"
    )

    assert isinstance(result, FusedKnowledge)
    assert result.confidence == 0.0


def test_merge_with_entity_alignment(fusion_engine):
    """测试带实体对齐的知识融合"""
    structured_knowledge = [
        {"hero": "Phantom Assassin", "item": "Black King Bar", "source": "opendota"}
    ]

    unstructured_knowledge = [
        {"hero": "PA", "item": "BKB", "source": "guide"}
    ]

    result = fusion_engine.merge(
        structured_knowledge=structured_knowledge,
        unstructured_knowledge=unstructured_knowledge,
        query="PA怎么出装？"
    )

    # 验证实体对齐
    assert result.structured_knowledge[0]["hero"] == "幻影刺客"
    assert result.structured_knowledge[0]["item"] == "BKB"


def test_fused_knowledge_to_dict(fusion_engine):
    """测试融合知识的字典转换"""
    result = fusion_engine.merge(
        structured_knowledge=[{"hero": "幻影刺客", "source": "opendota"}],
        unstructured_knowledge=[{"hero": "幻影刺客", "source": "guide"}],
        query="测试"
    )

    result_dict = result.to_dict()
    assert "query" in result_dict
    assert "structured_knowledge" in result_dict
    assert "unstructured_knowledge" in result_dict
    assert "confidence" in result_dict


def test_merge_preserves_sources(fusion_engine):
    """测试融合保留数据源"""
    structured_knowledge = [
        {"hero": "幻影刺客", "source": "opendota"}
    ]

    unstructured_knowledge = [
        {"hero": "幻影刺客", "source": "guide"}
    ]

    result = fusion_engine.merge(
        structured_knowledge=structured_knowledge,
        unstructured_knowledge=unstructured_knowledge,
        query="测试"
    )

    assert "opendota" in result.sources
    assert "guide" in result.sources
