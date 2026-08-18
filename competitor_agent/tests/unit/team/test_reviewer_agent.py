"""对抗式评审 Agent 测试（设计文档 49 §3.3）

Reviewer 纯代码证伪（无 LLM 调用）：关键数值反方核对 / 跨维度矛盾 / 置信度过低。
PARTIAL 低置信是诚实标注，不视为缺陷（保证 mock 零缺陷零回灌不变量）。
"""
from __future__ import annotations

from competitor_agent.domain_types.conflict import CrossDimensionConflict
from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.domain_types.observation import Observation, SourceEvidence
from competitor_agent.team.base_agent import AgentContext, AgentStatus
from competitor_agent.team.message_bus import MessageBus
from competitor_agent.team.reviewer_agent import ReviewerAgent


def _result(
    dimension: str,
    confidence: float = 0.8,
    details: dict | None = None,
    status: ResultStatus = ResultStatus.COMPLETE,
):
    return type(
        "R",
        (),
        {
            "dimension": dimension,
            "confidence": confidence,
            "details": details or {},
            "status": status,
        },
    )()


def _observation(dimension: str, raw_text: str):
    return type(
        "O",
        (),
        {
            "gap_field": dimension,
            "raw_text": raw_text,
        },
    )()


def _ctx(extra: dict | None = None):
    return AgentContext(task="t", strategy=None, session_id="s", max_retries=1, extra=extra or {})


class TestReview:
    def test_ok_when_no_issues(self):
        reviewer = ReviewerAgent(MessageBus())
        verdict = reviewer.review(
            _ctx(),
            [_result("pricing", details={"monthly_price_usd": 20})],
            [_observation("pricing", "Pro costs $20 per month")],
        )
        assert verdict.ok
        assert verdict.issues == []

    def test_low_confidence_complete_flagged(self):
        reviewer = ReviewerAgent(MessageBus(), min_confidence=0.3)
        verdict = reviewer.review(
            _ctx(),
            [_result("pricing", confidence=0.1)],
        )
        assert not verdict.ok
        assert verdict.issues[0].kind == "low_confidence"

    def test_partial_low_confidence_not_flagged(self):
        """PARTIAL 低置信是诚实标注，不视为缺陷（mock 口碑 0.1 PARTIAL 不触发回灌）。"""
        reviewer = ReviewerAgent(MessageBus(), min_confidence=0.3)
        verdict = reviewer.review(
            _ctx(),
            [_result("sentiment", confidence=0.1, status=ResultStatus.PARTIAL)],
        )
        assert verdict.ok

    def test_numeric_conflict_flagged(self):
        """details 声称 1000 但观测原文只有 20 → 关键数值无法回溯，需修订。"""
        reviewer = ReviewerAgent(MessageBus())
        verdict = reviewer.review(
            _ctx(),
            [_result("pricing", details={"monthly_price_usd": 1000})],
            [_observation("pricing", "Pro costs $20 per month")],
        )
        assert not verdict.ok
        assert verdict.issues[0].kind == "numeric_conflict"

    def test_cross_dimension_conflict_issue(self):
        reviewer = ReviewerAgent(MessageBus())
        conflict = CrossDimensionConflict(
            claim_key="stars",
            dimension_a="ecosystem",
            dimension_b="feature",
            value_a=100,
            value_b=9999,
            evidence_hashes=["h1"],
        )
        verdict = reviewer.review(_ctx(), [_result("pricing")], cross_dim_conflicts=[conflict])
        assert not verdict.ok
        assert verdict.issues[0].kind == "cross_dimension_conflict"

    def test_no_observation_for_dimension_skips_numeric(self):
        reviewer = ReviewerAgent(MessageBus())
        verdict = reviewer.review(
            _ctx(),
            [_result("feature", details={"stars": 1000})],
            [],  # 无该维度观测 → 数值核对跳过
        )
        assert verdict.ok


class TestRun:
    def test_run_returns_ok_verdict(self):
        reviewer = ReviewerAgent(MessageBus())
        result = reviewer.run(_ctx(extra={"results": [_result("pricing")]}))
        assert result.status == AgentStatus.SUCCESS
        assert result.payload.ok

    def test_run_no_results_degraded(self):
        reviewer = ReviewerAgent(MessageBus())
        result = reviewer.run(_ctx(extra={"results": []}))
        assert result.status == AgentStatus.DEGRADED
