"""FreshnessGate — 新鲜度驱动委派（设计文档 49 §3.2）

把维度 TTL 从"报告标注 / 定时重爬"（设计文档 26，事后过期重爬）提升到
**编排层委派**（委派期预防性跳过）：Collector 按维度新鲜度决定委派哪些缺口——
- 过期维度（age > TTL）→ ``stale``：优先委派采集；
- 新鲜维度（age ≤ TTL）→ ``fresh``：跳过采集，直接复用归档结论；
- 无归档信息（age 缺失）→ ``skip``：正常采集（默认行为）；
- 时间线变更事件（设计文档 26）命中维度 → 提权强制 ``stale`` 重采。

默认关闭（``orchestration.freshness_delegation.enabled: false``）：未装配时
编排器行为完全不变（零回归）。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from competitor_agent.domain_types.freshness import DEFAULT_TTL_DAYS
from competitor_agent.memory.timeline_memory import _EVENT_TYPE_BY_DIM, TimelineEvent


class FreshnessDecision(str, Enum):
    """委派决策：stale 采集（优先）/ fresh 跳过采集 / skip 正常采集"""

    STALE = "stale"
    FRESH = "fresh"
    SKIP = "skip"


@dataclass
class FreshnessDecisions:
    """按维度的委派决策结果"""

    decisions: dict[str, FreshnessDecision] = field(default_factory=dict)

    def get(self, dimension: str, default: FreshnessDecision = FreshnessDecision.SKIP) -> FreshnessDecision:
        return self.decisions.get(dimension, default)

    def fresh_dimensions(self) -> list[str]:
        return [d for d, v in self.decisions.items() if v == FreshnessDecision.FRESH]


class FreshnessGate:
    """按维度 TTL + 时间线事件判定委派策略（纯函数，可单测）。"""

    def __init__(self, ttl_days: dict[str, int] | None = None) -> None:
        self._ttl = dict(DEFAULT_TTL_DAYS)
        if ttl_days:
            self._ttl.update(ttl_days)

    def decide(
        self,
        planned_gaps: Sequence[object],
        archive_freshness: dict[str, float] | None = None,
        timeline_events: Sequence[TimelineEvent] | None = None,
    ) -> FreshnessDecisions:
        """按维度判定委派策略。

        Args:
            planned_gaps: 规划缺口（duck-type 出 field）。
            archive_freshness: 上次归档的最新维度年龄（dimension → 天），来自 ReportFreshness.dimension_ages。
            timeline_events: 竞品时间线变更事件（设计文档 26），命中维度提权强制重采。
        """
        archive = dict(archive_freshness or {})
        events = list(timeline_events or [])
        forced = self._timeline_hit_dimensions(events)

        decisions: dict[str, FreshnessDecision] = {}
        for gap in planned_gaps:
            dim = str(getattr(gap, "field", ""))
            if not dim:
                continue
            if dim in forced:
                decisions[dim] = FreshnessDecision.STALE
                continue
            age = archive.get(dim)
            if age is None:
                decisions[dim] = FreshnessDecision.SKIP
            elif float(age) > float(self._ttl.get(dim, DEFAULT_TTL_DAYS.get(dim, 30))):
                decisions[dim] = FreshnessDecision.STALE
            else:
                decisions[dim] = FreshnessDecision.FRESH
        return FreshnessDecisions(decisions)

    @staticmethod
    def _timeline_hit_dimensions(events: Sequence[TimelineEvent]) -> set[str]:
        """时间线事件命中维度：事件的 event_type 与该维度映射的事件类型一致。"""
        hit: set[str] = set()
        for dim, event_type in _EVENT_TYPE_BY_DIM.items():
            if any(e.event_type == event_type for e in events):
                hit.add(dim)
        return hit


__all__ = ["FreshnessDecision", "FreshnessDecisions", "FreshnessGate"]
