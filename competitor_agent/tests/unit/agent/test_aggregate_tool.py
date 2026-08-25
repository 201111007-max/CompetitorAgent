"""设计文档 62 M2 — aggregate_report 聚合工具单测。

覆盖：kind 校验（compare/position）、parts 空校验、聚合决策声明与引导回填、
``aggregate_payload_valid`` 轻量结构校验。
"""
from __future__ import annotations

import pytest
from competitor_agent.agent.aggregate_tool import (
    aggregate_payload_valid,
    make_aggregate_tool,
)


@pytest.fixture
def aggregate() -> object:
    return make_aggregate_tool()


def test_aggregate_position_default(aggregate: object) -> None:
    """kind 缺省为 position（普查格局），返回决策声明 + 引导结论段。"""
    out = aggregate(parts="[candidate cline] 定价…\n[candidate cursor] 定价…")
    assert "kind=position" in out
    assert "市场格局核心结论" in out
    assert "[candidate cline]" in out


def test_aggregate_compare_kind(aggregate: object) -> None:
    """kind=compare 显式对比明确声明。"""
    out = aggregate(
        parts="[a]\n[b]", dimensions=["feature", "pricing"], kind="compare"
    )
    assert "kind=compare" in out
    assert "feature、pricing" in out
    assert "best_per_dimension" in out


def test_aggregate_rejects_invalid_kind(aggregate: object) -> None:
    """非法 kind 抛 ValueError（可读回灌，Lead 可修正）。"""
    with pytest.raises(ValueError, match="kind 非法"):
        aggregate(parts="x", kind="rank")


def test_aggregate_rejects_empty_parts(aggregate: object) -> None:
    """parts 为空抛 ValueError，提示先完成候选分析再聚合。"""
    with pytest.raises(ValueError, match="parts 为空"):
        aggregate(parts="")


def test_aggregate_rejects_blank_parts(aggregate: object) -> None:
    """全空白 parts 同样拒绝。"""
    with pytest.raises(ValueError, match="parts 为空"):
        aggregate(parts="   ")


def test_aggregate_payload_valid_kinds() -> None:
    """载荷结构校验：仅 compare/position 合法。"""
    assert aggregate_payload_valid({"kind": "compare"}) is True
    assert aggregate_payload_valid({"kind": "position"}) is True
    assert aggregate_payload_valid({"kind": "rank"}) is False
    assert aggregate_payload_valid({}) is False