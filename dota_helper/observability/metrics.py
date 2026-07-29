"""MetricsCollector — 关键运行指标采集

采集 Token 消耗、耗时、置信度等指标，支持进程内聚合。
"""
import time
from collections import defaultdict
from statistics import mean, stdev
from typing import Any, Dict, List, Optional

from dota_helper.observability.logger import get_logger

logger = get_logger("observability.metrics")


class MetricsCollector:
    """关键运行指标采集器

    进程内聚合，支持 Counter/Gauge/Histogram 三种指标类型。
    """

    def __init__(self) -> None:
        """初始化指标采集器"""
        # Counter: 单调递增计数
        self._counters: Dict[str, float] = defaultdict(float)
        # Gauge: 可增可减的当前值
        self._gauges: Dict[str, float] = defaultdict(float)
        # Histogram: 分布统计
        self._histograms: Dict[str, List[float]] = defaultdict(list)

    def increment_counter(self, name: str, value: float = 1.0) -> None:
        """递增计数器

        Args:
            name: 指标名称
            value: 递增值（默认 1.0）
        """
        self._counters[name] += value

    def set_gauge(self, name: str, value: float) -> None:
        """设置 Gauge 值

        Args:
            name: 指标名称
            value: 当前值
        """
        self._gauges[name] = value

    def observe_histogram(self, name: str, value: float) -> None:
        """记录 Histogram 观测值

        Args:
            name: 指标名称
            value: 观测值
        """
        self._histograms[name].append(value)

    def get_counter(self, name: str) -> float:
        """获取计数器值

        Args:
            name: 指标名称

        Returns:
            float: 计数器当前值
        """
        return self._counters[name]

    def get_gauge(self, name: str) -> float:
        """获取 Gauge 值

        Args:
            name: 指标名称

        Returns:
            float: Gauge 当前值
        """
        return self._gauges[name]

    def get_histogram_summary(self, name: str) -> Dict[str, Any]:
        """获取 Histogram 统计摘要

        Args:
            name: 指标名称

        Returns:
            Dict[str, Any]: 统计摘要（count/mean/min/max/stdev）
        """
        values = self._histograms[name]
        if not values:
            return {"count": 0, "mean": 0.0, "min": 0.0, "max": 0.0, "stdev": 0.0}

        summary: Dict[str, Any] = {
            "count": len(values),
            "mean": mean(values),
            "min": min(values),
            "max": max(values),
        }
        if len(values) >= 2:
            summary["stdev"] = stdev(values)
        else:
            summary["stdev"] = 0.0

        return summary

    def to_dict(self) -> Dict[str, Any]:
        """导出所有指标为字典

        Returns:
            Dict[str, Any]: 指标字典
        """
        result: Dict[str, Any] = {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {},
        }
        for name in self._histograms:
            result["histograms"][name] = self.get_histogram_summary(name)
        return result

    def reset(self) -> None:
        """重置所有指标"""
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()


class Timer:
    """耗时测量上下文管理器

    自动记录耗时到 MetricsCollector 的 Histogram。

    Args:
        collector: MetricsCollector 实例
        name: 指标名称
    """

    def __init__(self, collector: MetricsCollector, name: str) -> None:
        """初始化计时器

        Args:
            collector: 指标采集器
            name: 指标名称
        """
        self._collector = collector
        self._name = name
        self._start: float = 0.0

    def __enter__(self) -> "Timer":
        """开始计时

        Returns:
            Timer: self
        """
        self._start = time.monotonic()
        return self

    def __exit__(self, *args: Any) -> None:
        """结束计时并记录"""
        elapsed_ms = (time.monotonic() - self._start) * 1000
        self._collector.observe_histogram(self._name, elapsed_ms)


# 全局单例
_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """获取全局指标采集器实例

    Returns:
        MetricsCollector: 全局单例
    """
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector
