"""置信度评估测试"""

import pytest
from knowledge.confidence_evaluator import ConfidenceEvaluator


@pytest.fixture
def confidence_evaluator():
    """创建置信度评估器实例"""
    return ConfidenceEvaluator()


def test_evaluate_high_confidence_source(confidence_evaluator):
    """测试高置信度数据源"""
    knowledge = {
        "source": "opendota",
        "hero": "幻影刺客",
        "item": "BKB"
    }

    confidence = confidence_evaluator.evaluate(knowledge)
    assert confidence >= 0.8


def test_evaluate_medium_confidence_source(confidence_evaluator):
    """测试中等置信度数据源"""
    knowledge = {
        "source": "guide",
        "hero": "幻影刺客",
        "item": "BKB"
    }

    confidence = confidence_evaluator.evaluate(knowledge)
    assert 0.5 <= confidence < 0.8


def test_evaluate_low_confidence_source(confidence_evaluator):
    """测试低置信度数据源"""
    knowledge = {
        "source": "unknown",
        "hero": "幻影刺客",
        "item": "BKB"
    }

    confidence = confidence_evaluator.evaluate(knowledge)
    assert confidence < 0.5


def test_evaluate_with_metadata(confidence_evaluator):
    """测试带元数据的置信度评估"""
    knowledge = {
        "source": "opendota",
        "hero": "幻影刺客",
        "item": "BKB",
        "win_rate": 0.65,
        "pick_rate": 0.8
    }

    confidence = confidence_evaluator.evaluate(knowledge)
    assert confidence >= 0.9


def test_evaluate_with_high_win_rate(confidence_evaluator):
    """测试高胜率知识的置信度"""
    knowledge = {
        "source": "guide",
        "hero": "幻影刺客",
        "item": "BKB",
        "win_rate": 0.75
    }

    confidence = confidence_evaluator.evaluate(knowledge)
    # 高胜率应该提升置信度
    assert confidence > 0.6


def test_evaluate_with_low_pick_rate(confidence_evaluator):
    """测试低选取率知识的置信度"""
    knowledge = {
        "source": "opendota",
        "hero": "幻影刺客",
        "item": "BKB",
        "pick_rate": 0.1
    }

    confidence = confidence_evaluator.evaluate(knowledge)
    # 低选取率应该降低置信度
    assert confidence < 0.9


def test_evaluate_dotabuff_source(confidence_evaluator):
    """测试 Dotabuff 数据源"""
    knowledge = {
        "source": "dotabuff",
        "hero": "幻影刺客",
        "item": "BKB"
    }

    confidence = confidence_evaluator.evaluate(knowledge)
    assert 0.8 <= confidence < 0.9


def test_evaluate_wiki_source(confidence_evaluator):
    """测试 Wiki 数据源"""
    knowledge = {
        "source": "wiki",
        "hero": "幻影刺客",
        "item": "BKB"
    }

    confidence = confidence_evaluator.evaluate(knowledge)
    assert 0.6 <= confidence < 0.8


def test_evaluate_user_source(confidence_evaluator):
    """测试用户贡献数据源"""
    knowledge = {
        "source": "user",
        "hero": "幻影刺客",
        "item": "BKB"
    }

    confidence = confidence_evaluator.evaluate(knowledge)
    assert 0.4 <= confidence < 0.6


def test_evaluate_with_recency(confidence_evaluator):
    """测试带时效性的置信度评估"""
    knowledge = {
        "source": "guide",
        "hero": "幻影刺客",
        "item": "BKB",
        "timestamp": 1700000000  # 较旧的时间戳
    }

    confidence = confidence_evaluator.evaluate(knowledge)
    # 较旧的知识应该有较低的置信度
    assert confidence < 0.7
