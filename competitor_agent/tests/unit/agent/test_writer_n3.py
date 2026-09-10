"""设计文档 88 §6 —— N3 引用锚定后处理单测。

覆盖：[n] 占位 → 槽位 evidence_urls markdown 链接、越界序号删除、prose 自写 URL 剔除、
先剔 URL 后锚定的顺序（自写 URL 与合法占位共存）。
"""

from __future__ import annotations

from competitor_agent.agent.writer_slots import NarrativeSlot, anchor_citations
from competitor_agent.domain_types.distilled import DimensionFacts, DistilledFact


def _slot() -> NarrativeSlot:
    return NarrativeSlot(
        slot_id="executive_summary",
        heading="执行摘要",
        input_facts=[
            DimensionFacts(
                dimension="pricing",
                confidence=0.8,
                status="complete",
                summary="s",
                facts=[
                    DistilledFact(
                        term="t",
                        label="l",
                        value="v",
                        evidence_urls=("https://a.com/p", "https://b.com/q"),
                    )
                ],
                evidence_urls=["https://a.com/p", "https://b.com/q"],
            )
        ],
    )


class TestN3Anchor:
    def test_placeholder_anchored(self) -> None:
        out = anchor_citations(_slot(), "Pro 档定价见官方页 [1]，另有佐证 [2]。")
        assert "[1](https://a.com/p)" in out
        assert "[2](https://b.com/q)" in out

    def test_out_of_range_placeholder_removed(self) -> None:
        out = anchor_citations(_slot(), "来源 [9] 越界。")
        assert "[9]" not in out
        assert "越界" in out

    def test_self_written_url_stripped(self) -> None:
        """URL 权威在代码：writer 自写 URL 一律剔除。"""
        out = anchor_citations(_slot(), "详见 https://evil.com/x 页面。")
        assert "https://evil.com" not in out
        assert "页面" in out

    def test_strip_before_anchor_order(self) -> None:
        """先剔 URL 再锚定：自写 URL 与合法占位共存时互不干扰。"""
        out = anchor_citations(_slot(), "官方 [1] 而非 https://fake.com 所述。")
        assert "[1](https://a.com/p)" in out
        assert "https://fake.com" not in out

    def test_no_urls_all_placeholders_removed(self) -> None:
        empty = NarrativeSlot(slot_id="s", heading="h", input_facts=[])
        out = anchor_citations(empty, "引用 [1] 无证据。")
        assert "[1]" not in out
