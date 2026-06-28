"""
学习引擎 - 根据反馈数据更新策略参数

职责：
- 实时增量学习：根据单次反馈微调引擎权重
- 定期批量校准：根据历史反馈批量更新规则参数
- 边界保护：防止权重/参数超出合理范围
"""

import time
from typing import Dict, Any, Optional
import logging

from feedback.store import FeedbackRecord
from feedback.evaluator import EffectEvaluator
from feedback.strategy_params import StrategyParams

logger = logging.getLogger(__name__)


class LearningEngine:
    """学习引擎"""

    def __init__(
        self,
        evaluator: EffectEvaluator,
        strategy_params: StrategyParams,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        初始化学习引擎

        Args:
            evaluator: 效果评估器
            strategy_params: 策略参数管理
            config: 配置字典
        """
        self.evaluator = evaluator
        self.strategy_params = strategy_params
        self.config = config or {}

        # 实时学习配置
        realtime_config = self.config.get("realtime", {})
        self.learning_rate = realtime_config.get("learning_rate", 0.01)
        self.min_weight = realtime_config.get("min_weight", 0.1)
        self.max_weight = realtime_config.get("max_weight", 0.7)

        # 批量校准配置
        calibration_config = self.config.get("calibration", {})
        self.calibration_lookback_hours = calibration_config.get("lookback_hours", 24)
        self.calibration_min_feedback = calibration_config.get("min_feedback_count", 10)
        self.calibration_threshold = calibration_config.get("positive_rate_threshold", 0.6)
        self.calibration_step = calibration_config.get("adjustment_step", 0.05)

        # 参数边界保护
        self.param_min_ratio = 0.5  # 参数最小值为默认值的 50%
        self.param_max_ratio = 1.5  # 参数最大值为默认值的 150%

        logger.info("学习引擎初始化完成")

    def realtime_update(self, feedback: FeedbackRecord) -> None:
        """
        实时增量学习：根据单次反馈微调引擎权重

        算法：
        1. 目标引擎权重按 learning_rate * score 调整
        2. 其他引擎权重按原比例分摊差值（保持总和为 1.0）
        3. 边界保护

        Args:
            feedback: 反馈记录
        """
        if not feedback.engine:
            logger.warning("反馈记录缺少引擎信息，跳过实时更新")
            return

        # 获取当前权重
        current_weights = self.strategy_params.get_engine_weights()
        current_weight = current_weights.get(feedback.engine, 0.3)

        # 计算权重调整
        adjustment = self.learning_rate * feedback.score
        new_weight = current_weight + adjustment

        # 边界保护
        new_weight = max(self.min_weight, min(self.max_weight, new_weight))

        # 计算差值
        delta = new_weight - current_weight
        if abs(delta) < 1e-9:
            return

        # 其他引擎按原比例分摊差值
        other_engines = {k: v for k, v in current_weights.items() if k != feedback.engine}
        if other_engines:
            other_total = sum(other_engines.values())
            if other_total > 0:
                for engine, w in other_engines.items():
                    # 按原比例分摊
                    ratio = w / other_total
                    adjusted_w = w - delta * ratio
                    adjusted_w = max(self.min_weight, min(self.max_weight, adjusted_w))
                    self.strategy_params.update_engine_weight(engine, adjusted_w)

        # 更新目标引擎权重
        self.strategy_params.update_engine_weight(feedback.engine, new_weight)

        # 保存更新
        self.strategy_params.save()

        logger.debug(f"实时更新引擎权重: {feedback.engine} {current_weight:.3f} -> {new_weight:.3f}")

    def batch_calibration(self) -> None:
        """
        定期批量校准：根据历史反馈更新规则参数
        """
        # 计算回溯时间
        since = time.time() - (self.calibration_lookback_hours * 3600)

        # 获取规则维度的效果评估
        rule_stats = self.evaluator.evaluate_rules(since=since)

        if not rule_stats:
            logger.info("无规则反馈数据，跳过批量校准")
            return

        # 遍历每个规则
        for rule_name, stats in rule_stats.items():
            # 检查反馈数量是否足够
            if stats.count < self.calibration_min_feedback:
                logger.debug(f"规则 {rule_name} 反馈数量不足 ({stats.count} < {self.calibration_min_feedback})")
                continue

            # 根据正反馈率调整参数
            if stats.positive_rate < self.calibration_threshold:
                # 效果差：减少该规则的触发频率
                self._adjust_rule_param(rule_name, direction="decrease")
            elif stats.positive_rate > self.calibration_threshold + 0.1:
                # 效果好：增加该规则的触发频率
                self._adjust_rule_param(rule_name, direction="increase")

        # 更新统计信息
        overall_stats = self.evaluator.get_overall_stats(since=since)
        self.strategy_params.update_stats(overall_stats)

        # 保存更新
        self.strategy_params.save()

        logger.info(f"批量校准完成: 处理 {len(rule_stats)} 个规则")

    def _adjust_rule_param(self, rule_name: str, direction: str) -> None:
        """
        调整规则参数

        Args:
            rule_name: 规则名称
            direction: 调整方向 ("increase" | "decrease")
        """
        # 目前只支持调整 low_health_threshold 和 recommendation_cooldown
        # 其他规则参数暂不支持自动调整
        param_mapping = {
            "血量预警": "low_health_threshold",
            "low_health": "low_health_threshold",
        }

        param_name = param_mapping.get(rule_name)
        if not param_name:
            logger.debug(f"规则 {rule_name} 不支持自动参数调整")
            return

        # 获取当前值
        current_value = self.strategy_params.get_rule_param(param_name)
        if current_value is None:
            return

        # 计算调整步长
        step = self.calibration_step * current_value

        # 应用调整
        if direction == "increase":
            new_value = current_value + step
        else:  # decrease
            new_value = current_value - step

        # 边界保护
        default_value = self.strategy_params.default_rule_params.get(param_name, current_value)
        min_value = default_value * self.param_min_ratio
        max_value = default_value * self.param_max_ratio
        new_value = max(min_value, min(max_value, new_value))

        # 更新参数
        self.strategy_params.update_rule_param(
            param_name=param_name,
            value=new_value,
            confidence=0.5  # 简单置信度
        )

        logger.info(f"批量校准规则参数: {param_name} {current_value:.3f} -> {new_value:.3f} ({direction})")

    def _normalize_weights(self) -> None:
        """归一化引擎权重（确保总和为 1.0）"""
        current_weights = self.strategy_params.get_engine_weights()

        if not current_weights:
            return

        total = sum(current_weights.values())
        if total == 0:
            return

        # 归一化
        normalized = {
            engine: weight / total
            for engine, weight in current_weights.items()
        }

        # 更新权重
        for engine, weight in normalized.items():
            self.strategy_params.update_engine_weight(engine, weight)

        logger.debug(f"归一化引擎权重: {normalized}")
