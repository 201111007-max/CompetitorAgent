"""新鲜度驱动委派测试（设计文档 49 §3.2）

FreshnessGate 按维度 TTL + 时间线事件判定委派策略：
过期 → stale 优先采集；新鲜 → fresh 跳过采集复用归档；无归档 → skip 正常采集；
时间线事件命中 → 提权强制 stale 重采。默认关闭时编排器行为不变（零回归）。
"""
from __future__ import annotations

from competitor_agent.core.freshness_gate import FreshnessDecision, FreshnessGate
from competitor_agent.domain_types.freshness import DEFAULT_TTL_DAYS
from competitor_agent.memory.timeline_memory import TimelineEvent


class _Gap:
    def __init__(self, field: str) -> None:
        self.field = field


def test_fresh_dimension_skips_collection():
    gate = FreshnessGate()
    decisions = gate.decide(
        [_Gap("pricing")], archive_freshness={"pricing": 1}
    )
    assert decisions.get("pricing") == FreshnessDecision.FRESH


def test_stale_when_age_exceeds_ttl():
    gate = FreshnessGate()
    decisions = gate.decide(
        [_Gap("pricing")], archive_freshness={"pricing": 10}
    )
    assert decisions.get("pricing") == FreshnessDecision.STALE


def test_skip_when_no_archive_age():
    gate = FreshnessGate()
    decisions = gate.decide([_Gap("pricing")])
    assert decisions.get("pricing") == FreshnessDecision.SKIP


def test_timeline_event_forces_stale_even_when_fresh():
    gate = FreshnessGate()
    decisions = gate.decide(
        [_Gap("pricing")],
        archive_freshness={"pricing": 1},
        timeline_events=[
            TimelineEvent(
                competitor="cursor", event_type="price_change", summary="价格变更"
            )
        ],
    )
    assert decisions.get("pricing") == FreshnessDecision.STALE


def test_ttl_boundary_fresh_equal():
    gate = FreshnessGate()
    decisions = gate.decide(
        [_Gap("pricing")], archive_freshness={"pricing": float(DEFAULT_TTL_DAYS["pricing"])}
    )
    assert decisions.get("pricing") == FreshnessDecision.FRESH


def test_custom_ttl_override():
    gate = FreshnessGate(ttl_days={"pricing": 30})
    decisions = gate.decide([_Gap("pricing")], archive_freshness={"pricing": 15})
    assert decisions.get("pricing") == FreshnessDecision.FRESH


def test_fresh_dimensions_helper():
    gate = FreshnessGate()
    decisions = gate.decide(
        [_Gap("pricing"), _Gap("feature"), _Gap("sentiment")],
        archive_freshness={"pricing": 1, "feature": 100, "sentiment": 2},
    )
    assert decisions.fresh_dimensions() == ["pricing", "sentiment"]


def test_decision_default_is_skip():
    gate = FreshnessGate()
    decisions = gate.decide([_Gap("pricing")])
    assert decisions.get("unknown_dim") == FreshnessDecision.SKIP
