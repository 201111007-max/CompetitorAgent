"""跨维度冲突检测测试（设计文档 49 §3.1）

同源（content_hash 一致）同事实键在不同维度结论值不一致 → 记 CrossDimensionConflict；
与同维度多来源仲裁（FactValidator.arbitrate）互补，属编排层核对。
"""
from __future__ import annotations

import pytest

from competitor_agent.domain_types.conflict import CrossDimensionConflict, ConflictRegistry, detect_conflicts_across
from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.domain_types.report import DimensionResult

_HASH = "abc123"


def _result(
    dimension: str,
    details: dict,
    hashes: list[str] | None = None,
    confidence: float = 0.8,
) -> DimensionResult:
    return DimensionResult(
        dimension=dimension,
        summary=f"{dimension} 结论",
        details=details,
        confidence=confidence,
        status=ResultStatus.COMPLETE,
        evidence_hashes=hashes if hashes is not None else [_HASH],
    )


class TestConflictRegistry:
    def test_same_source_same_key_diff_values_detected(self):
        registry = ConflictRegistry()
        registry.register(
            _result("pricing", {"monthly_price_usd": 20})
        )
        registry.register(_result("feature", {"monthly_price_usd": 40}))
        conflicts = registry.detect()
        assert len(conflicts) == 1
        c = conflicts[0]
        assert c.claim_key == "monthly_price_usd"
        assert {c.dimension_a, c.dimension_b} == {"pricing", "feature"}
        assert c.value_a != c.value_b
        assert _HASH in c.evidence_hashes

    def test_same_value_no_conflict(self):
        registry = ConflictRegistry()
        registry.register(_result("pricing", {"monthly_price_usd": 20}))
        registry.register(_result("feature", {"monthly_price_usd": 20}))
        assert registry.detect() == []

    def test_different_sources_no_conflict(self):
        registry = ConflictRegistry()
        registry.register(_result("pricing", {"monthly_price_usd": 20}, hashes=["h1"]))
        registry.register(_result("feature", {"monthly_price_usd": 40}, hashes=["h2"]))
        assert registry.detect() == []

    def test_nested_details_flattened(self):
        registry = ConflictRegistry()
        registry.register(_result("pricing", {"tiers": [{"monthly_price_usd": 20}]}))
        registry.register(_result("feature", {"billing": {"monthly_price_usd": 30}}))
        conflicts = registry.detect()
        assert len(conflicts) == 1
        assert conflicts[0].claim_key == "monthly_price_usd"

    def test_ignores_non_shared_and_bool_values(self):
        registry = ConflictRegistry()
        # "ratio" 不在共享事实键；bool 值不参与核对
        registry.register(_result("pricing", {"polarity_ratio": {"pos": 0.8}, "score": True}))
        registry.register(_result("feature", {"polarity_ratio": {"pos": 0.2}, "score": False}))
        assert registry.detect() == []

    def test_register_requires_evidence_hash(self):
        registry = ConflictRegistry()
        no_hash = _result("pricing", {"monthly_price_usd": 20}, hashes=[])
        registry.register(no_hash)
        registry.register(_result("feature", {"monthly_price_usd": 40}))
        assert registry.detect() == []

    def test_same_dimension_same_source_overwrites_no_self_conflict(self):
        registry = ConflictRegistry()
        registry.register(_result("pricing", {"monthly_price_usd": 20}))
        registry.register(_result("pricing", {"monthly_price_usd": 30}))
        assert registry.detect() == []

    def test_summary_property_readable(self):
        registry = ConflictRegistry()
        registry.register(_result("pricing", {"monthly_price_usd": 20}))
        registry.register(_result("feature", {"monthly_price_usd": 40}))
        summary = registry.detect()[0].summary
        assert "pricing" in summary
        assert "feature" in summary
        assert "monthly_price_usd" in summary


class TestDetectConflictsAcross:
    """设计文档 49 ReAct 路径：以 (claim_key × 证据 URL) 为同源键检测跨维度冲突。"""

    @staticmethod
    def _payload(dimension: str, details: dict, urls: list[str] | None = None) -> dict:
        return {
            "dimension": dimension,
            "details": details,
            "evidence_urls": urls if urls is not None else ["https://www.cursor.com"],
        }

    def test_same_url_same_key_diff_values_detected(self):
        conflicts = detect_conflicts_across(
            [
                self._payload("pricing", {"stars": 1000}),
                self._payload("ecosystem", {"stars": 9999}),
            ]
        )
        assert len(conflicts) == 1
        assert conflicts[0].claim_key == "stars"

    def test_different_urls_no_conflict(self):
        conflicts = detect_conflicts_across(
            [
                self._payload("pricing", {"stars": 1000}, urls=["https://a.com"]),
                self._payload("ecosystem", {"stars": 9999}, urls=["https://b.com"]),
            ]
        )
        assert conflicts == []

    def test_no_evidence_urls_no_conflict(self):
        conflicts = detect_conflicts_across(
            [
                self._payload("pricing", {"stars": 1000}, urls=[]),
                self._payload("ecosystem", {"stars": 9999}, urls=[]),
            ]
        )
        assert conflicts == []

    def test_same_value_no_conflict(self):
        conflicts = detect_conflicts_across(
            [
                self._payload("pricing", {"stars": 1000}),
                self._payload("ecosystem", {"stars": 1000}),
            ]
        )
        assert conflicts == []
