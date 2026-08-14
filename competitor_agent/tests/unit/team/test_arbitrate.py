"""Validator 冲突仲裁测试（设计文档 33 §3.3）

同维度多来源冲突 → 按 置信度 > 证据源 trust > 时间新鲜度 取优；
被丢弃候选保留为 conflict_evidence（不静默丢弃）。
"""
from __future__ import annotations

from competitor_agent.domain_types.observation import SourceEvidence
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.team.validator_agent import FactValidator


def _result(dimension: str, confidence: float, trust: float, summary: str) -> DimensionResult:
    ev = SourceEvidence(source_name=f"src-{trust}", trust_level=trust)
    return DimensionResult(
        dimension=dimension,
        summary=summary,
        confidence=confidence,
        evidence=[ev],
    )


class TestArbitrate:
    def test_single_source_returned_unchanged(self):
        r = _result("pricing", 0.8, 0.9, "A")
        out = FactValidator().arbitrate([r])
        assert out == {"pricing": r}
        assert r.conflict_evidence == []

    def test_picks_highest_confidence(self):
        v = FactValidator()
        low = _result("pricing", 0.4, 0.9, "低置信")
        high = _result("pricing", 0.9, 0.5, "高置信")
        out = v.arbitrate([low, high])
        assert out["pricing"] is high

    def test_breaks_confidence_tie_by_trust(self):
        v = FactValidator()
        low_trust = _result("pricing", 0.8, 0.4, "低可信源")
        high_trust = _result("pricing", 0.8, 0.9, "高可信源")
        out = v.arbitrate([low_trust, high_trust])
        assert out["pricing"] is high_trust

    def test_conflicts_preserved_in_conflict_evidence(self):
        v = FactValidator()
        winner = _result("pricing", 0.9, 0.9, "官方定价")
        loser = _result("pricing", 0.5, 0.9, "第三方传闻")
        out = v.arbitrate([loser, winner])
        assert out["pricing"] is winner
        assert len(winner.conflict_evidence) == 1
        assert "第三方传闻" in winner.conflict_evidence[0]

    def test_multi_dimension_arbitrated_independently(self):
        v = FactValidator()
        p_win = _result("pricing", 0.9, 0.9, "P")
        p_lose = _result("pricing", 0.3, 0.9, "p2")
        f_win = _result("feature", 0.8, 0.9, "F")
        f_lose = _result("feature", 0.6, 0.9, "f2")
        out = v.arbitrate([p_lose, p_win, f_lose, f_win])
        assert set(out) == {"pricing", "feature"}
        assert out["pricing"] is p_win
        assert out["feature"] is f_win

    def test_newest_timestamp_breaks_full_tie(self):
        from datetime import datetime, timedelta, timezone

        v = FactValidator()
        old = _result("pricing", 0.7, 0.9, "old")
        old.timestamp = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        new = _result("pricing", 0.7, 0.9, "new")
        out = v.arbitrate([old, new])
        assert out["pricing"] is new
