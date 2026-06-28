"""
反馈采集器测试
"""

import pytest
import tempfile
import time
from pathlib import Path

from feedback.store import FeedbackStore
from feedback.collector import FeedbackCollector


class TestFeedbackCollector:
    """测试反馈采集器"""

    @pytest.fixture
    def temp_db(self):
        """创建临时数据库"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_feedback.db"
            store = FeedbackStore(db_path=str(db_path))
            yield store

    @pytest.fixture
    def collector(self, temp_db):
        """创建采集器实例"""
        return FeedbackCollector(store=temp_db)

    def test_record_and_collect_explicit(self, collector):
        """测试记录推荐并采集显式反馈"""
        # 记录推荐
        collector.record_recommendation(
            recommendation_id="rec-001",
            engine="rule",
            event_type="low_health",
            rule_name="health_warning"
        )
        
        # 采集显式反馈
        record = collector.collect_explicit_feedback(
            recommendation_id="rec-001",
            score=4,
            comment="很有帮助"
        )
        
        assert record is not None
        assert record.recommendation_id == "rec-001"
        assert record.feedback_type == "explicit"
        assert record.score == 0.5  # (4-3)/2 = 0.5
        assert record.engine == "rule"
        assert record.metadata.get("comment") == "很有帮助"

    def test_record_and_collect_implicit(self, collector):
        """测试记录推荐并采集隐式反馈"""
        # 记录推荐
        collector.record_recommendation(
            recommendation_id="rec-002",
            engine="data",
            event_type="stack_neutral"
        )
        
        # 采集隐式反馈（采纳）
        record = collector.collect_implicit_feedback(
            recommendation_id="rec-002",
            behavior_type="adopt"
        )
        
        assert record is not None
        assert record.recommendation_id == "rec-002"
        assert record.feedback_type == "implicit"
        assert record.score == 1.0  # adopt_score
        assert record.engine == "data"
        assert record.metadata.get("behavior_type") == "adopt"

    def test_collect_without_record(self, collector):
        """测试采集未记录的推荐反馈"""
        # 尝试采集未记录的推荐
        record = collector.collect_explicit_feedback(
            recommendation_id="non-existent",
            score=3
        )
        
        assert record is None

    def test_cache_cleanup(self, collector):
        """测试缓存清理"""
        # 记录超过最大缓存数量的推荐
        for i in range(1100):
            collector.record_recommendation(
                recommendation_id=f"rec-{i}",
                engine="rule",
                event_type="test"
            )
        
        # 验证缓存被清理
        assert len(collector._recommendation_cache) < 1100

    def test_implicit_behavior_types(self, collector):
        """测试不同隐式反馈行为类型"""
        behaviors = {
            "adopt": 1.0,
            "partial_adopt": 0.5,
            "ignore": -0.2,
            "reverse": -0.5
        }
        
        for behavior, expected_score in behaviors.items():
            collector.record_recommendation(
                recommendation_id=f"rec-{behavior}",
                engine="rule",
                event_type="test"
            )
            
            record = collector.collect_implicit_feedback(
                recommendation_id=f"rec-{behavior}",
                behavior_type=behavior
            )
            
            assert record is not None
            assert record.score == expected_score
