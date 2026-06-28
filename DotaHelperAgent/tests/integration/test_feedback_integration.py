"""
反馈系统集成测试

验证端到端流程：
1. EventTrigger 生成推荐 -> 注册到 FeedbackCollector
2. 显式反馈提交 -> 实时更新引擎权重
3. 隐式反馈提交 -> 实时更新引擎权重
4. 批量校准 -> 更新规则参数
5. DecisionFusion 使用动态权重
6. RuleEngine 使用动态规则参数
"""

import pytest
import time
import tempfile
import os
from pathlib import Path
from unittest.mock import MagicMock

from feedback.store import FeedbackStore, FeedbackRecord
from feedback.collector import FeedbackCollector
from feedback.evaluator import EffectEvaluator
from feedback.strategy_params import StrategyParams
from feedback.learning_engine import LearningEngine


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def feedback_system(temp_dir):
    """搭建完整反馈系统"""
    db_path = os.path.join(temp_dir, "feedback.db")
    config_path = os.path.join(temp_dir, "learned_strategy.yaml")

    store = FeedbackStore(db_path=db_path)
    strategy_params = StrategyParams(config_path=config_path)
    collector = FeedbackCollector(store=store)
    evaluator = EffectEvaluator(store=store)
    learning_engine = LearningEngine(
        evaluator=evaluator,
        strategy_params=strategy_params,
        config={
            "realtime": {"learning_rate": 0.01, "min_weight": 0.1, "max_weight": 0.7},
            "calibration": {
                "lookback_hours": 24,
                "min_feedback_count": 3,
                "positive_rate_threshold": 0.6,
                "adjustment_step": 0.05,
            },
        },
    )

    return {
        "store": store,
        "strategy_params": strategy_params,
        "collector": collector,
        "evaluator": evaluator,
        "learning_engine": learning_engine,
    }


class TestEndToEndFeedbackFlow:
    """端到端反馈流程测试"""

    def test_recommendation_to_feedback_registration(self, feedback_system):
        """测试推荐注册到反馈采集器"""
        collector = feedback_system["collector"]

        # 模拟 EventTrigger 注册推荐上下文
        collector.record_recommendation(
            recommendation_id="rec-001",
            engine="rule",
            event_type="low_health",
            rule_name="血量预警",
            context={"recommendation": "血量较低，建议回城", "confidence": 0.9},
        )

        # 验证推荐已注册
        assert "rec-001" in collector._recommendation_cache
        cached = collector._recommendation_cache["rec-001"]
        assert cached["engine"] == "rule"
        assert cached["event_type"] == "low_health"

    def test_explicit_feedback_flow(self, feedback_system):
        """测试显式反馈完整流程"""
        collector = feedback_system["collector"]
        store = feedback_system["store"]
        learning_engine = feedback_system["learning_engine"]
        strategy_params = feedback_system["strategy_params"]

        # 1. 注册推荐
        collector.record_recommendation(
            recommendation_id="rec-002",
            engine="data",
            event_type="item_purchase",
        )

        # 2. 提交显式反馈（5星好评）
        record = collector.collect_explicit_feedback(
            recommendation_id="rec-002", score=5, comment="很好"
        )
        assert record is not None
        assert record.feedback_type == "explicit"
        assert record.engine == "data"
        assert record.score == 1.0  # 归一化后

        # 3. 实时更新
        old_weights = strategy_params.get_engine_weights()
        learning_engine.realtime_update(record)
        new_weights = strategy_params.get_engine_weights()

        # data 引擎权重应该增加
        assert new_weights.get("data", 0) >= old_weights.get("data", 0)

        # 4. 验证存储
        records = store.get_by_engine("data")
        assert len(records) >= 1

    def test_implicit_feedback_flow(self, feedback_system):
        """测试隐式反馈完整流程"""
        collector = feedback_system["collector"]
        learning_engine = feedback_system["learning_engine"]
        strategy_params = feedback_system["strategy_params"]

        # 1. 注册推荐
        collector.record_recommendation(
            recommendation_id="rec-003", engine="llm", event_type="stack_camp"
        )

        # 2. 提交隐式反馈（采纳）
        record = collector.collect_implicit_feedback(
            recommendation_id="rec-003", behavior_type="adopt"
        )
        assert record is not None
        assert record.feedback_type == "implicit"
        assert record.score == 1.0

        # 3. 实时更新
        old_weight = strategy_params.get_engine_weights().get("llm", 0.3)
        learning_engine.realtime_update(record)
        new_weight = strategy_params.get_engine_weights().get("llm", 0.3)
        assert new_weight >= old_weight

    def test_negative_feedback_decreases_weight(self, feedback_system):
        """测试负反馈降低引擎权重"""
        collector = feedback_system["collector"]
        learning_engine = feedback_system["learning_engine"]
        strategy_params = feedback_system["strategy_params"]

        # 注册推荐
        collector.record_recommendation(
            recommendation_id="rec-004", engine="rule", event_type="low_health"
        )

        # 提交负反馈（1星差评）
        record = collector.collect_explicit_feedback(
            recommendation_id="rec-004", score=1
        )
        assert record.score == -1.0  # 归一化后

        # 实时更新
        old_weight = strategy_params.get_engine_weights().get("rule", 0.3)
        learning_engine.realtime_update(record)
        new_weight = strategy_params.get_engine_weights().get("rule", 0.3)
        assert new_weight < old_weight

    def test_batch_calibration(self, feedback_system):
        """测试批量校准流程"""
        collector = feedback_system["collector"]
        learning_engine = feedback_system["learning_engine"]
        strategy_params = feedback_system["strategy_params"]

        # 注册多个推荐并提交反馈
        for i in range(5):
            rec_id = f"rec-cal-{i}"
            collector.record_recommendation(
                recommendation_id=rec_id,
                engine="rule",
                event_type="low_health",
                rule_name="血量预警",
            )
            # 全部提交差评（正反馈率 < 阈值）
            collector.collect_explicit_feedback(recommendation_id=rec_id, score=1)

        # 执行批量校准
        old_threshold = strategy_params.get_rule_param("low_health_threshold", 0.3)
        learning_engine.batch_calibration()
        new_threshold = strategy_params.get_rule_param("low_health_threshold", 0.3)

        # 差评多 -> 阈值应该降低（减少触发）
        assert new_threshold <= old_threshold

    def test_strategy_params_persistence(self, feedback_system, temp_dir):
        """测试策略参数持久化"""
        strategy_params = feedback_system["strategy_params"]

        # 更新权重
        strategy_params.update_engine_weight("rule", 0.35)
        strategy_params.update_rule_param("low_health_threshold", 0.25)
        strategy_params.save()

        # 重新加载
        new_params = StrategyParams(
            config_path=os.path.join(temp_dir, "learned_strategy.yaml")
        )
        assert new_params.get_engine_weights().get("rule") == pytest.approx(0.35)
        assert new_params.get_rule_param("low_health_threshold") == pytest.approx(0.25)

    def test_unknown_recommendation_returns_none(self, feedback_system):
        """测试未注册的推荐 ID 提交反馈返回 None"""
        collector = feedback_system["collector"]

        record = collector.collect_explicit_feedback(
            recommendation_id="non-existent", score=5
        )
        assert record is None

    def test_evaluator_aggregation(self, feedback_system):
        """测试评估器聚合"""
        collector = feedback_system["collector"]
        evaluator = feedback_system["evaluator"]

        # 注册并提交多个反馈
        for i in range(3):
            rec_id = f"rec-agg-{i}"
            collector.record_recommendation(
                recommendation_id=rec_id, engine="data", event_type="roshan"
            )
            collector.collect_explicit_feedback(recommendation_id=rec_id, score=4)

        # 评估引擎
        engine_stats = evaluator.evaluate_engines()
        assert "data" in engine_stats
        assert engine_stats["data"].count == 3

        # 评估场景
        scenario_stats = evaluator.evaluate_scenarios()
        assert "roshan" in scenario_stats

    def test_multiple_engines_weight_adjustment(self, feedback_system):
        """测试多引擎权重调整保持平衡"""
        collector = feedback_system["collector"]
        learning_engine = feedback_system["learning_engine"]
        strategy_params = feedback_system["strategy_params"]

        # 注册三个引擎的推荐
        for engine in ["rule", "data", "llm"]:
            collector.record_recommendation(
                recommendation_id=f"rec-{engine}", engine=engine, event_type="test"
            )

        # 给 data 引擎好评
        record = collector.collect_explicit_feedback(
            recommendation_id="rec-data", score=5
        )
        learning_engine.realtime_update(record)

        weights = strategy_params.get_engine_weights()
        # 所有权重应在 [min_weight, max_weight] 范围内
        for w in weights.values():
            assert 0.1 <= w <= 0.7
