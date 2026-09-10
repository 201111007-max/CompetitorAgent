"""设计文档 88 §4.1 —— core/report_aggregator 聚合层单测。

覆盖：合并顺序确定（= 输入顺序）、置信度夹取/非法值兜底、details 非空零证据封顶、
evidence_urls 单字符串归一（doc 87 C1 回归）、planned 未产出 → gaps_pending、
跨维度同源冲突 → conflict_note 非空、缺 dimension 名条目跳过。
"""

from __future__ import annotations

from competitor_agent.core.report_aggregator import (
    AggregateResult,
    aggregate_researcher_results,
    dimension_from_item,
    planned_dimensions,
)
from competitor_agent.domain_types.enums import ResultStatus


def _item(
    dim: str,
    *,
    confidence: object = 0.8,
    details: dict | None = None,
    urls: object = None,
) -> dict:
    return {
        "dimension": dim,
        "summary": f"{dim} 结论",
        "details": details or {},
        "confidence": confidence,
        "evidence_urls": urls if urls is not None else [],
    }


class TestAggregateOrder:
    def test_order_matches_input(self) -> None:
        items = [_item("feature"), _item("pricing"), _item("roadmap")]
        agg = aggregate_researcher_results(items, None)
        assert [d.dimension for d in agg.dimensions] == ["feature", "pricing", "roadmap"]

    def test_item_without_dimension_skipped(self) -> None:
        items = [_item("pricing"), _item("  "), {"summary": "无 dimension 名"}]
        agg = aggregate_researcher_results(items, None)
        assert [d.dimension for d in agg.dimensions] == ["pricing"]

    def test_empty_items(self) -> None:
        agg = aggregate_researcher_results([], None)
        assert agg == AggregateResult()


class TestConfidence:
    def test_clamped_to_unit_interval(self) -> None:
        high = dimension_from_item(_item("pricing", confidence=1.7))
        low = dimension_from_item(_item("pricing", confidence=-0.3))
        assert high is not None and high.confidence == 1.0
        assert low is not None and low.confidence == 0.0

    def test_invalid_confidence_defaults_05(self) -> None:
        dr = dimension_from_item(_item("pricing", confidence="high"))
        assert dr is not None and dr.confidence == 0.5

    def test_details_without_evidence_capped(self) -> None:
        dr = dimension_from_item(_item("pricing", confidence=0.9, details={"plans": []}))
        assert dr is not None
        assert dr.confidence == 0.5
        assert dr.status == ResultStatus.COMPLETE

    def test_details_with_evidence_not_capped(self) -> None:
        dr = dimension_from_item(
            _item("pricing", confidence=0.9, details={"plans": []}, urls=["https://a.com"])
        )
        assert dr is not None and dr.confidence == 0.9


class TestEvidenceUrls:
    def test_single_str_url_not_char_iterated(self) -> None:
        """doc 87 §1.4-C1 回归：字符串 URL 按整体一项，不拆字符。"""
        dr = dimension_from_item(_item("pricing", urls="https://example.com/pricing"))
        assert dr is not None
        assert [e.url for e in dr.evidence] == ["https://example.com/pricing"]
        assert dr.evidence_hashes == ["https://example.com/pricing"]


class TestGapsReconciliation:
    def test_planned_not_produced_becomes_gaps(self) -> None:
        plan = {"dimensions": ["pricing", "feature", "roadmap"]}
        agg = aggregate_researcher_results([_item("pricing")], plan)
        assert [g.field for g in agg.gaps_pending] == ["feature", "roadmap"]
        assert all(g.priority == 5 for g in agg.gaps_pending)

    def test_all_produced_no_gaps(self) -> None:
        plan = {"dimensions": ["pricing"]}
        agg = aggregate_researcher_results([_item("pricing")], plan)
        assert agg.gaps_pending == []

    def test_planned_dimensions_non_dict_plan(self) -> None:
        assert planned_dimensions(None) == []
        assert planned_dimensions("pricing") == []
        assert planned_dimensions({"dimensions": "pricing"}) == []


class TestConflictNote:
    def test_same_source_conflict_produces_note(self) -> None:
        url = "https://vendor.com/pricing"
        items = [
            _item("pricing", details={"monthly_price_usd": 20}, urls=[url]),
            _item("performance", details={"monthly_price_usd": 30}, urls=[url]),
        ]
        agg = aggregate_researcher_results(items, None)
        assert agg.conflict_note.startswith("## 跨维度冲突备注")

    def test_no_shared_source_no_note(self) -> None:
        items = [
            _item("pricing", details={"monthly_price_usd": 20}, urls=["https://a.com"]),
            _item("performance", details={"monthly_price_usd": 30}, urls=["https://b.com"]),
        ]
        agg = aggregate_researcher_results(items, None)
        assert agg.conflict_note == ""
