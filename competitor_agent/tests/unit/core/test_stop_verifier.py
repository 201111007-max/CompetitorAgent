"""core/stop_verifier.py 单测"""
from competitor_agent.core.stop_verifier import StopVerifier
from competitor_agent.domain_types import GapStatus, InfoGap, SourceEvidence
from competitor_agent.interfaces.context import BudgetState


def _gap(field, confidence=0.0, status=GapStatus.OPEN, evidence=None):
    return InfoGap(field=field, confidence=confidence, status=status, evidence=evidence or [])


def _evidence():
    return SourceEvidence(source_name="docs", content_hash="h")


class TestStopVerifierRequiredDimensions:
    def test_missing_required_dimension_blocks(self):
        v = StopVerifier(required_dimensions=["pricing", "feature"])
        gaps = [
            _gap("pricing", confidence=0.9, status=GapStatus.CLOSED, evidence=[_evidence()]),
        ]
        d = v.verify(gaps, BudgetState())
        assert not d.should_stop
        assert d.reason == "required_dimension_missing"

    def test_low_confidence_blocks(self):
        v = StopVerifier(required_dimensions=["pricing"], min_confidence=0.6)
        gaps = [_gap("pricing", confidence=0.4, status=GapStatus.CLOSED, evidence=[_evidence()])]
        d = v.verify(gaps, BudgetState())
        assert not d.should_stop
        assert d.reason == "core_confidence_low"

    def test_low_evidence_ratio_blocks(self):
        v = StopVerifier(required_dimensions=["pricing"], min_evidence_ratio=0.7)
        gaps = [
            _gap("pricing", confidence=0.9, status=GapStatus.CLOSED, evidence=[_evidence()]),
            _gap("feature", confidence=0.9, status=GapStatus.CLOSED, evidence=[]),  # 无证据
        ]
        d = v.verify(gaps, BudgetState())
        assert not d.should_stop
        assert d.reason == "evidence_ratio_low"

    def test_approves_when_all_satisfied(self):
        v = StopVerifier(required_dimensions=["pricing"], min_confidence=0.6, min_evidence_ratio=0.5)
        gaps = [
            _gap("pricing", confidence=0.9, status=GapStatus.CLOSED, evidence=[_evidence()]),
            _gap("feature", confidence=0.7, status=GapStatus.CONFIRMED, evidence=[_evidence()]),
        ]
        d = v.verify(gaps, BudgetState())
        assert d.should_stop
        assert d.reason == "verifier_approved"

    def test_no_closed_gaps_still_approves_if_required_satisfied(self):
        # 没有已关闭缺口时证据率检查跳过（全 open 则预算条件会拦）
        v = StopVerifier(required_dimensions=["pricing"], min_evidence_ratio=0.7)
        gaps = [_gap("pricing", confidence=0.8, status=GapStatus.OPEN)]
        d = v.verify(gaps, BudgetState())
        assert d.should_stop