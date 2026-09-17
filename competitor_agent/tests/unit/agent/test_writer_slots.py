"""设计文档 88 §4.2 —— writer_slots 槽位契约单测。

覆盖：build_slots 槽序与 input_facts 切分（exec/conclusion=全量、dimension=单维）、
build_writer_messages 含系统标记与 untrusted 包裹、槽 evidence_urls 保序去重、
MOCK_SLOT_PROSE 无数字无 URL（N2/N3 自洽）。
"""

from __future__ import annotations

import re

from competitor_agent.agent.writer_slots import (
    MOCK_SLOT_PROSE,
    build_slots,
    build_writer_messages,
    dimension_slot_id,
)
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.distilled import distill_report
from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.domain_types.observation import SourceEvidence
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult


def _report() -> CompetitorReport:
    evidence = [SourceEvidence(source_name="web", url="https://a.com", access_time="", trust_level=0.8)]
    return CompetitorReport(
        competitor=Competitor(name="cursor"),
        dimension_results=[
            DimensionResult(
                dimension="pricing",
                summary="Pro 档 $20/月",
                details={"plans": [{"name": "Pro", "monthly_price_usd": 20}]},
                confidence=0.8,
                status=ResultStatus.COMPLETE,
                evidence=evidence,
            ),
            DimensionResult(
                dimension="feature",
                summary="支持 MCP",
                details={"features": ["支持 MCP 协议"]},
                confidence=0.6,
                status=ResultStatus.COMPLETE,
            ),
        ],
    )


class TestBuildSlots:
    def test_slot_order_and_count(self) -> None:
        slots = build_slots(_report(), distill_report(_report()))
        assert [s.slot_id for s in slots] == [
            "executive_summary",
            "dimension_insight:pricing",
            "dimension_insight:feature",
            "market_conclusion",
        ]

    def test_input_facts_partition(self) -> None:
        slots = build_slots(_report(), distill_report(_report()))
        by_id = {s.slot_id: s for s in slots}
        assert [df.dimension for df in by_id["executive_summary"].input_facts] == ["pricing", "feature"]
        assert [df.dimension for df in by_id["market_conclusion"].input_facts] == ["pricing", "feature"]
        assert [df.dimension for df in by_id["dimension_insight:pricing"].input_facts] == ["pricing"]

    def test_evidence_urls_ordered_dedup(self) -> None:
        slot = build_slots(_report(), distill_report(_report()))[0]
        assert slot.evidence_urls == ["https://a.com"]


class TestWriterMessages:
    def test_system_marker_and_untrusted_wrap(self) -> None:
        slot = build_slots(_report(), distill_report(_report()))[1]
        messages = build_writer_messages(slot)
        assert messages[0]["role"] == "system"
        assert "叙事槽位撰写器" in messages[0]["content"]
        assert "pricing 维度解读" in messages[0]["content"]
        assert "<untrusted_data>" in messages[1]["content"]
        assert "Pro 档月价" in messages[1]["content"]  # 蒸馏事实进入 payload

    def test_mock_prose_self_consistent(self) -> None:
        """MOCK_SLOT_PROSE 无数字（N2 必过）无 URL 无 [n] 占位（N3 无操作）。"""
        assert not re.search(r"\d", MOCK_SLOT_PROSE)
        assert "http" not in MOCK_SLOT_PROSE
        assert "[" not in MOCK_SLOT_PROSE

    def test_dimension_slot_id(self) -> None:
        assert dimension_slot_id("pricing") == "dimension_insight:pricing"


class TestComparisonMessages:
    """设计文档 95 —— comparison 形态 writer messages（横向格局指令 + competitor 载荷）。"""

    def _comparison_slot(self):
        from competitor_agent.agent.writer_slots import SLOT_CONCLUSION, NarrativeSlot

        facts = distill_report(_report())
        for df in facts:
            df.competitor = "cursor"
        return NarrativeSlot(
            slot_id=SLOT_CONCLUSION, heading="市场格局核心结论", input_facts=facts
        )

    def test_comparison_system_instruction(self) -> None:
        slot = self._comparison_slot()
        messages = build_writer_messages(slot, comparison=True)
        system = messages[0]["content"]
        assert "叙事槽位撰写器" in system  # mock 分发标记不动
        assert "市场格局核心结论" in system
        assert "维度 × 竞品" in system
        assert "横向" in system
        assert "只能依据下方" in system and "[n] 占位" in system  # 硬性规则不动

    def test_comparison_payload_carries_competitor(self) -> None:
        slot = self._comparison_slot()
        messages = build_writer_messages(slot, comparison=True)
        assert '"competitor": "cursor"' in messages[1]["content"]

    def test_single_path_payload_has_no_competitor_key(self) -> None:
        """单竞品路径 facts 不回填 competitor → payload 形态不变。"""
        slot = build_slots(_report(), distill_report(_report()))[1]
        messages = build_writer_messages(slot)
        assert '"competitor"' not in messages[1]["content"]
