"""
反馈存储层测试
"""

import pytest
import tempfile
import time
from pathlib import Path

from feedback.store import FeedbackStore, FeedbackRecord


class TestFeedbackStore:
    """测试反馈存储"""

    @pytest.fixture
    def temp_db(self):
        """创建临时数据库"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_feedback.db"
            store = FeedbackStore(db_path=str(db_path))
            yield store

    @pytest.fixture
    def sample_record(self):
        """创建示例反馈记录"""
        return FeedbackRecord(
            feedback_id="test-001",
            recommendation_id="rec-001",
            feedback_type="explicit",
            score=0.5,
            engine="rule",
            event_type="low_health",
            rule_name="health_warning",
            context={"health_percent": 0.25},
            timestamp=time.time(),
            metadata={"comment": "测试反馈"}
        )

    def test_save_and_query_by_engine(self, temp_db, sample_record):
        """测试保存和按引擎查询"""
        temp_db.save(sample_record)
        
        records = temp_db.get_by_engine("rule")
        assert len(records) == 1
        assert records[0].feedback_id == "test-001"
        assert records[0].engine == "rule"

    def test_query_by_rule(self, temp_db, sample_record):
        """测试按规则查询"""
        temp_db.save(sample_record)
        
        records = temp_db.get_by_rule("health_warning")
        assert len(records) == 1
        assert records[0].rule_name == "health_warning"

    def test_query_by_event_type(self, temp_db, sample_record):
        """测试按事件类型查询"""
        temp_db.save(sample_record)
        
        records = temp_db.get_by_event_type("low_health")
        assert len(records) == 1
        assert records[0].event_type == "low_health"

    def test_aggregate_by_engine(self, temp_db):
        """测试按引擎聚合"""
        # 创建多条记录
        for i in range(3):
            record = FeedbackRecord(
                feedback_id=f"test-{i}",
                recommendation_id=f"rec-{i}",
                feedback_type="explicit",
                score=0.5 if i < 2 else -0.3,
                engine="rule",
                event_type="low_health",
                timestamp=time.time()
            )
            temp_db.save(record)
        
        stats = temp_db.get_aggregate("engine")
        assert "rule" in stats
        assert stats["rule"].count == 3
        assert stats["rule"].avg_score == pytest.approx((0.5 + 0.5 - 0.3) / 3, rel=1e-2)

    def test_cleanup_old_records(self, temp_db):
        """测试清理过期记录"""
        # 创建一条旧记录
        old_record = FeedbackRecord(
            feedback_id="old-001",
            recommendation_id="rec-old",
            feedback_type="explicit",
            score=0.5,
            engine="rule",
            event_type="low_health",
            timestamp=time.time() - 40 * 86400  # 40天前
        )
        temp_db.save(old_record)
        
        # 创建一条新记录
        new_record = FeedbackRecord(
            feedback_id="new-001",
            recommendation_id="rec-new",
            feedback_type="explicit",
            score=0.5,
            engine="rule",
            event_type="low_health",
            timestamp=time.time()
        )
        temp_db.save(new_record)
        
        # 清理30天前的记录
        deleted = temp_db.cleanup(max_age_days=30)
        assert deleted == 1
        
        # 验证只剩新记录
        records = temp_db.get_by_engine("rule")
        assert len(records) == 1
        assert records[0].feedback_id == "new-001"
