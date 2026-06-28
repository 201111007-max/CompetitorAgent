"""
效果评估器测试
"""

import pytest
import tempfile
import time
from pathlib import Path

from feedback.store import FeedbackStore, FeedbackRecord
from feedback.evaluator import EffectEvaluator


class TestEffectEvaluator:
    """测试效果评估器"""

    @pytest.fixture
    def temp_db(self):
        """创建临时数据库"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_feedback.db"
            store = FeedbackStore(db_path=str(db_path))
            yield store

    @pytest.fixture
    def evaluator(self, temp_db):
        """创建评估器实例"""
        return EffectEvaluator(store=temp_db)

    def test_evaluate_engines(self, evaluator, temp_db):
        """测试引擎维度评估"""
        # 创建不同引擎的反馈
        engines = ["rule", "data", "llm"]
        for engine in engines:
            for i in range(3):
                record = FeedbackRecord(
                    feedback_id=f"{engine}-{i}",
                    recommendation_id=f"rec-{engine}-{i}",
                    feedback_type="explicit",
                    score=0.5 if i < 2 else -0.3,
                    engine=engine,
                    event_type="test",
                    timestamp=time.time()
                )
                temp_db.save(record)
        
        # 评估引擎效果
        stats = evaluator.evaluate_engines()
        
        assert len(stats) == 3
        for engine in engines:
            assert engine in stats
            assert stats[engine].count == 3

    def test_evaluate_rules(self, evaluator, temp_db):
        """测试规则维度评估"""
        # 创建不同规则的反馈
        rules = ["health_warning", "stack_neutral"]
        for rule in rules:
            for i in range(2):
                record = FeedbackRecord(
                    feedback_id=f"{rule}-{i}",
                    recommendation_id=f"rec-{rule}-{i}",
                    feedback_type="explicit",
                    score=0.5,
                    engine="rule",
                    event_type="test",
                    rule_name=rule,
                    timestamp=time.time()
                )
                temp_db.save(record)
        
        # 评估规则效果
        stats = evaluator.evaluate_rules()
        
        assert len(stats) == 2
        for rule in rules:
            assert rule in stats
            assert stats[rule].count == 2

    def test_get_engine_performance(self, evaluator, temp_db):
        """测试获取单个引擎性能"""
        # 创建规则引擎的反馈
        for i in range(5):
            record = FeedbackRecord(
                feedback_id=f"rule-{i}",
                recommendation_id=f"rec-{i}",
                feedback_type="explicit",
                score=0.8 if i < 4 else -0.5,
                engine="rule",
                event_type="test",
                timestamp=time.time()
            )
            temp_db.save(record)
        
        # 获取规则引擎性能
        stats = evaluator.get_engine_performance("rule")
        
        assert stats.count == 5
        assert stats.avg_score == pytest.approx((0.8 * 4 - 0.5) / 5, rel=1e-2)
        assert stats.positive_rate == 0.8  # 4/5 正反馈

    def test_get_overall_stats(self, evaluator, temp_db):
        """测试获取整体统计"""
        # 创建多个引擎的反馈
        for engine in ["rule", "data"]:
            for i in range(3):
                record = FeedbackRecord(
                    feedback_id=f"{engine}-{i}",
                    recommendation_id=f"rec-{engine}-{i}",
                    feedback_type="explicit",
                    score=0.5,
                    engine=engine,
                    event_type="test",
                    timestamp=time.time()
                )
                temp_db.save(record)
        
        # 获取整体统计
        stats = evaluator.get_overall_stats()
        
        assert stats["total_count"] == 6
        assert stats["avg_score"] == 0.5
