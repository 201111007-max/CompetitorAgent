"""
学习引擎测试
"""

import pytest
import tempfile
import time
from pathlib import Path

from feedback.store import FeedbackStore, FeedbackRecord
from feedback.evaluator import EffectEvaluator
from feedback.strategy_params import StrategyParams
from feedback.learning_engine import LearningEngine


class TestLearningEngine:
    """测试学习引擎"""

    @pytest.fixture
    def temp_db(self):
        """创建临时数据库"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_feedback.db"
            store = FeedbackStore(db_path=str(db_path))
            yield store

    @pytest.fixture
    def temp_config(self):
        """创建临时配置文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "learned_strategy.yaml"
            params = StrategyParams(config_path=str(config_path))
            yield params

    @pytest.fixture
    def learning_engine(self, temp_db, temp_config):
        """创建学习引擎实例"""
        evaluator = EffectEvaluator(store=temp_db)
        return LearningEngine(
            evaluator=evaluator,
            strategy_params=temp_config,
            config={
                "realtime": {
                    "learning_rate": 0.01,
                    "min_weight": 0.1,
                    "max_weight": 0.7
                },
                "calibration": {
                    "lookback_hours": 24,
                    "min_feedback_count": 10,
                    "positive_rate_threshold": 0.6,
                    "adjustment_step": 0.05
                }
            }
        )

    def test_realtime_update_positive(self, learning_engine, temp_config):
        """测试实时更新（正反馈）"""
        # 创建正反馈记录
        record = FeedbackRecord(
            feedback_id="test-001",
            recommendation_id="rec-001",
            feedback_type="explicit",
            score=0.8,
            engine="rule",
            event_type="test",
            timestamp=time.time()
        )
        
        # 记录初始权重
        initial_weight = temp_config.get_engine_weights()["rule"]
        
        # 实时更新
        learning_engine.realtime_update(record)
        
        # 验证权重增加
        new_weight = temp_config.get_engine_weights()["rule"]
        assert new_weight > initial_weight

    def test_realtime_update_negative(self, learning_engine, temp_config):
        """测试实时更新（负反馈）"""
        # 创建负反馈记录
        record = FeedbackRecord(
            feedback_id="test-002",
            recommendation_id="rec-002",
            feedback_type="explicit",
            score=-0.5,
            engine="rule",
            event_type="test",
            timestamp=time.time()
        )
        
        # 记录初始权重
        initial_weight = temp_config.get_engine_weights()["rule"]
        
        # 实时更新
        learning_engine.realtime_update(record)
        
        # 验证权重减少
        new_weight = temp_config.get_engine_weights()["rule"]
        assert new_weight < initial_weight

    def test_realtime_update_weight_bounds(self, learning_engine, temp_config):
        """测试实时更新权重边界"""
        # 连续发送大量正反馈
        for i in range(100):
            record = FeedbackRecord(
                feedback_id=f"test-{i}",
                recommendation_id=f"rec-{i}",
                feedback_type="explicit",
                score=1.0,
                engine="rule",
                event_type="test",
                timestamp=time.time()
            )
            learning_engine.realtime_update(record)
        
        # 验证权重不超过最大值
        weight = temp_config.get_engine_weights()["rule"]
        assert weight <= 0.7  # max_weight

    def test_batch_calibration(self, learning_engine, temp_db, temp_config):
        """测试批量校准"""
        # 创建足够数量的反馈（超过 min_feedback_count）
        for i in range(15):
            record = FeedbackRecord(
                feedback_id=f"test-{i}",
                recommendation_id=f"rec-{i}",
                feedback_type="explicit",
                score=0.5 if i < 10 else -0.3,  # 67% 正反馈率
                engine="rule",
                event_type="test",
                rule_name="health_warning",
                timestamp=time.time()
            )
            temp_db.save(record)
        
        # 执行批量校准
        learning_engine.batch_calibration()
        
        # 验证配置已保存
        assert temp_config.config_path.exists()

    def test_batch_calibration_insufficient_feedback(self, learning_engine, temp_db):
        """测试批量校准（反馈数量不足）"""
        # 创建少量反馈（少于 min_feedback_count）
        for i in range(5):
            record = FeedbackRecord(
                feedback_id=f"test-{i}",
                recommendation_id=f"rec-{i}",
                feedback_type="explicit",
                score=0.5,
                engine="rule",
                event_type="test",
                timestamp=time.time()
            )
            temp_db.save(record)
        
        # 执行批量校准（应该跳过）
        learning_engine.batch_calibration()
        
        # 验证没有错误发生
