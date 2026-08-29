"""设计文档 67 §3.2 — human-in-the-loop 审批单测。

规则触发（低置信/price_change/新增竞品）→ pending_review；不触发 → approved；
approve/reject 状态流转 + reviewer_note 落 JSON；旧 JSON（无 status）向后兼容读为 approved。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from competitor_agent.core.approval_gate import (
    APPROVED,
    PENDING_REVIEW,
    ApprovalPolicy,
    decide_approval,
    decide_weekly_approval,
    report_json_path,
    report_status,
    set_report_status,
)
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult


def _report(overall: float = 0.8, dims: list[tuple[str, float, str]] | None = None) -> CompetitorReport:
    dims = dims or [("pricing", 0.8, "complete")]
    return CompetitorReport(
        competitor=Competitor(name="cursor"),
        overall_confidence=overall,
        dimension_results=[
            DimensionResult(dimension=d, confidence=c, status=ResultStatus(s))
            for d, c, s in dims
        ],
    )


def _event(kind: str) -> object:
    return type("E", (), {"event_type": kind})()


class TestDecideApproval:
    def test_no_trigger_approved(self):
        assert decide_approval(_report(0.8)) == APPROVED

    def test_low_overall_confidence_pending(self):
        assert decide_approval(_report(0.3)) == PENDING_REVIEW

    def test_low_partial_dimension_pending(self):
        r = _report(dims=[("pricing", 0.2, "partial"), ("feature", 0.9, "complete")])
        assert decide_approval(r) == PENDING_REVIEW

    def test_price_change_pending(self):
        assert decide_approval(_report(0.8), timeline_events=[_event("price_change")]) == PENDING_REVIEW

    def test_score_change_pending(self):
        assert decide_approval(_report(0.8), timeline_events=[_event("score_change")]) == PENDING_REVIEW

    def test_non_trigger_event_approved(self):
        assert decide_approval(_report(0.8), timeline_events=[_event("feature_added")]) == APPROVED

    def test_new_competitor_pending(self):
        assert decide_approval(_report(0.8), is_new_competitor=True) == PENDING_REVIEW

    def test_policy_disables_rules(self):
        policy = ApprovalPolicy(review_low_confidence=False, review_price_change=False,
                                review_new_competitor=False)
        assert decide_approval(_report(0.3), timeline_events=[_event("price_change")],
                               is_new_competitor=True, policy=policy) == APPROVED


class TestDecideWeeklyApproval:
    def test_high_impact_pending(self):
        assert decide_weekly_approval({"high_impact": True}) == PENDING_REVIEW

    def test_no_impact_approved(self):
        assert decide_weekly_approval({"high_impact": False}) == APPROVED


class TestReportStatusIO:
    def test_missing_file_defaults_approved(self, tmp_path: Path):
        assert report_status(tmp_path / "nope.json") == APPROVED

    def test_old_json_without_status_reads_approved(self, tmp_path: Path):
        path = tmp_path / "cursor.json"
        path.write_text(json.dumps({"competitor": "cursor"}), encoding="utf-8")
        assert report_status(path) == APPROVED

    def test_approve_writes_status_and_note(self, tmp_path: Path):
        path = tmp_path / "cursor.json"
        path.write_text(json.dumps({"competitor": "cursor", "status": PENDING_REVIEW}), encoding="utf-8")
        data = set_report_status(path, APPROVED, reviewer_note="ok 数据已核对")
        assert data["status"] == APPROVED
        assert data["reviewer_note"] == "ok 数据已核对"
        assert data["reviewed_at"]
        reloaded = json.loads(path.read_text(encoding="utf-8"))
        assert reloaded["status"] == APPROVED

    def test_reject_writes_rejected(self, tmp_path: Path):
        path = tmp_path / "cursor.json"
        path.write_text(json.dumps({"competitor": "cursor"}), encoding="utf-8")
        data = set_report_status(path, "rejected", reviewer_note="证据不足")
        assert data["status"] == "rejected"

    def test_invalid_status_raises(self, tmp_path: Path):
        path = tmp_path / "cursor.json"
        path.write_text(json.dumps({"competitor": "cursor"}), encoding="utf-8")
        with pytest.raises(ValueError):
            set_report_status(path, "weird")

    def test_report_json_path_matches_exporter(self, tmp_path: Path):
        from competitor_agent.core.report_archiver import resolve_output_dir

        out = resolve_output_dir(tmp_path / "out")
        assert report_json_path("Cursor AI", tmp_path / "out") == out / "Cursor_AI.json"


class TestDecisionWithRealStatus:
    def test_partial_status_value_matches(self):
        # ResultStatus.PARTIAL.value == "partial"，与 decide_approval 判定一致
        assert ResultStatus.PARTIAL.value == "partial"
