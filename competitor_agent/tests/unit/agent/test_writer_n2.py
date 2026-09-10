"""设计文档 88 §6 —— N2 保真校验单测。

覆盖：清单外数字违规、三形态（{:g}/{:.2f}/int）放行、单位上下文不进 token（$20/月）、
派生安全数（维度数/证据数/置信度）放行、年份等不可派生数字违规。
"""

from __future__ import annotations

from competitor_agent.agent.writer_slots import (
    NarrativeSlot,
    slot_allowed_numbers,
    validate_slot_prose,
)
from competitor_agent.domain_types.distilled import DimensionFacts, DistilledFact


def _slot() -> NarrativeSlot:
    return NarrativeSlot(
        slot_id="dimension_insight:pricing",
        heading="pricing 维度解读",
        input_facts=[
            DimensionFacts(
                dimension="pricing",
                confidence=0.8,
                status="complete",
                summary="Pro 档 $20/月",
                facts=[
                    DistilledFact(
                        term="plan:pro:monthly",
                        label="Pro 档月价",
                        value="20",
                        unit="USD/month",
                        numeric=20.0,
                        evidence_urls=("https://a.com",),
                    ),
                    DistilledFact(
                        term="plan:free:monthly",
                        label="Free 档月价",
                        value="0",
                        unit="USD/month",
                        numeric=0.0,
                    ),
                ],
                evidence_urls=["https://a.com"],
            )
        ],
    )


class TestN2Violations:
    def test_unlisted_number_flagged(self) -> None:
        violations = validate_slot_prose(_slot(), "Pro 档 $30/月，性价比一般。")
        assert violations == ["30"]

    def test_year_flagged(self) -> None:
        """年份不可从 facts 派生 → 违规（prompt 侧亦禁写，双保险）。"""
        violations = validate_slot_prose(_slot(), "截至 2026 年，Pro 档 $20/月。")
        assert violations == ["2026"]

    def test_multiple_violations_deduped(self) -> None:
        violations = validate_slot_prose(_slot(), "涨价 30 又 30，另收 99。")
        assert violations == ["30", "99"]


class TestN2Allowed:
    def test_fact_number_three_forms(self) -> None:
        for prose in ("Pro 档 $20/月。", "Pro 档月价 20.00 美元。", "月付 20"):
            assert validate_slot_prose(_slot(), prose) == [], prose

    def test_unit_context_not_in_token(self) -> None:
        """$ 与 /月 是上下文不进 token（口径：数字必须来自 facts，单位归 prompt 管）。"""
        assert validate_slot_prose(_slot(), "仅需 $20/月即可解锁 Pro。") == []

    def test_derived_safe_numbers(self) -> None:
        """置信度/维度数/证据计数可直接派生 → 放行。"""
        slot = _slot()
        allowed = slot_allowed_numbers(slot, overall_confidence=0.7)
        assert validate_slot_prose(slot, "置信度 0.8，综合 0.70，共 1 个维度 1 条证据。", allowed=allowed) == []

    def test_zero_value_fact(self) -> None:
        assert validate_slot_prose(_slot(), "Free 档 0 美元。") == []
