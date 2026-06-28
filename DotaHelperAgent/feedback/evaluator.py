"""
效果评估器 - 聚合反馈数据，计算各维度的效果指标

职责：
- 按引擎维度聚合反馈
- 按规则维度聚合反馈
- 按场景维度聚合反馈
- 计算时间趋势
"""

import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import logging

from feedback.store import FeedbackStore, FeedbackRecord, AggregateStats

logger = logging.getLogger(__name__)


class EffectEvaluator:
    """效果评估器"""

    def __init__(self, store: FeedbackStore):
        """
        初始化效果评估器

        Args:
            store: 反馈存储实例
        """
        self.store = store
        logger.info("效果评估器初始化完成")

    def evaluate_engines(self, since: Optional[float] = None) -> Dict[str, AggregateStats]:
        """
        评估引擎效果

        Args:
            since: 起始时间戳

        Returns:
            引擎维度的聚合统计
        """
        return self.store.get_aggregate("engine", since=since)

    def evaluate_rules(self, since: Optional[float] = None) -> Dict[str, AggregateStats]:
        """
        评估规则效果

        Args:
            since: 起始时间戳

        Returns:
            规则维度的聚合统计
        """
        return self.store.get_aggregate("rule_name", since=since)

    def evaluate_scenarios(self, since: Optional[float] = None) -> Dict[str, AggregateStats]:
        """
        评估场景效果

        Args:
            since: 起始时间戳

        Returns:
            场景维度的聚合统计
        """
        return self.store.get_aggregate("event_type", since=since)

    def get_engine_performance(self, engine: str, since: Optional[float] = None) -> AggregateStats:
        """
        获取单个引擎的性能指标

        Args:
            engine: 引擎名称
            since: 起始时间戳

        Returns:
            聚合统计
        """
        records = self.store.get_by_engine(engine, since=since)
        return self._calculate_stats(records)

    def get_rule_performance(self, rule_name: str, since: Optional[float] = None) -> AggregateStats:
        """
        获取单个规则的性能指标

        Args:
            rule_name: 规则名称
            since: 起始时间戳

        Returns:
            聚合统计
        """
        records = self.store.get_by_rule(rule_name, since=since)
        return self._calculate_stats(records)

    def get_scenario_performance(self, event_type: str, since: Optional[float] = None) -> AggregateStats:
        """
        获取单个场景的性能指标

        Args:
            event_type: 事件类型
            since: 起始时间戳

        Returns:
            聚合统计
        """
        records = self.store.get_by_event_type(event_type, since=since)
        return self._calculate_stats(records)

    def _calculate_stats(self, records: List[FeedbackRecord]) -> AggregateStats:
        """
        计算统计指标

        Args:
            records: 反馈记录列表

        Returns:
            聚合统计
        """
        if not records:
            return AggregateStats()

        count = len(records)
        scores = [r.score for r in records]
        avg_score = sum(scores) / count
        positive_count = sum(1 for s in scores if s > 0)
        positive_rate = positive_count / count

        # 计算标准差
        if count > 1:
            variance = sum((s - avg_score) ** 2 for s in scores) / (count - 1)
            std_score = variance ** 0.5
        else:
            std_score = 0.0

        return AggregateStats(
            count=count,
            avg_score=avg_score,
            positive_rate=positive_rate,
            std_score=std_score,
            last_updated=time.time()
        )

    def get_overall_stats(self, since: Optional[float] = None) -> Dict[str, Any]:
        """
        获取整体统计

        Args:
            since: 起始时间戳

        Returns:
            整体统计字典
        """
        engine_stats = self.evaluate_engines(since=since)

        total_count = sum(s.count for s in engine_stats.values())
        if total_count == 0:
            return {
                "total_count": 0,
                "avg_score": 0.0,
                "positive_rate": 0.0,
            }

        weighted_avg = sum(s.avg_score * s.count for s in engine_stats.values()) / total_count
        weighted_positive = sum(s.positive_rate * s.count for s in engine_stats.values()) / total_count

        return {
            "total_count": total_count,
            "avg_score": weighted_avg,
            "positive_rate": weighted_positive,
        }
