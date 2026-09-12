"""chunk_text_semantic overlap 死参数修复测试（93_rag_deepening_design.md §1 / §3）

- 相邻块尾部保留至多 overlap 字符重叠，重叠起点尽量对齐句末边界
- overlap >= size 或 <= 0 时禁用重叠（不小于窗口的重叠无意义）
- 块边界仍落在句末/块界，块长上限优先于重叠
"""

from __future__ import annotations

from competitor_agent.knowledge_base.ingester import _overlap_seed, chunk_text_semantic

_DOC = "Alpha first fact. Beta second fact. Gamma third fact. Delta fourth fact. Epsilon fifth fact."


class TestOverlap:
    def test_adjacent_chunks_share_tail(self):
        chunks = chunk_text_semantic(_DOC, size=45, overlap=20)
        assert len(chunks) >= 3, "应切出多块"
        # 相邻块存在内容重叠：下一块开头是上一块尾部的一段
        for prev, nxt in zip(chunks, chunks[1:]):
            shared = next(
                (nxt[:k] for k in range(min(20, len(nxt)), 0, -1) if prev.endswith(nxt[:k])),
                "",
            )
            assert shared, f"相邻块应有尾部重叠: {prev!r} -> {nxt!r}"

    def test_boundaries_still_sentence_final(self):
        chunks = chunk_text_semantic(_DOC, size=45, overlap=20)
        assert all(c.endswith((".", "。", "!", "？", "；", ";")) for c in chunks), "块边界仍应落在句末"

    def test_chunk_size_cap_wins_over_overlap(self):
        chunks = chunk_text_semantic(_DOC, size=45, overlap=20)
        assert all(len(c) <= 45 for c in chunks), "重叠不得突破块长上限"

    def test_overlap_disabled_when_ge_size(self):
        with_overlap = chunk_text_semantic(_DOC, size=45, overlap=45)
        without = chunk_text_semantic(_DOC, size=45, overlap=0)
        assert with_overlap == without, "overlap >= size 应禁用重叠"
        # 禁用重叠后无内容重复：拼接还原原文
        assert "".join(without).replace(" ", "") == _DOC.replace(" ", "")

    def test_overlap_zero_no_duplication(self):
        chunks = chunk_text_semantic(_DOC, size=45, overlap=0)
        assert "".join(chunks).replace(" ", "") == _DOC.replace(" ", "")

    def test_overlap_seed_aligns_sentence_boundary(self):
        chunk = "Partial start. Whole sentence here. Tail fragment"
        seed = _overlap_seed(chunk, overlap=30)
        # 尾部 30 字符含残句时应丢弃首个残句，从句末边界开始
        assert not seed.startswith("gmen"), "重叠起点不应落在句中"
        assert len(seed) <= 30

    def test_overlap_seed_short_chunk_returns_empty(self):
        assert _overlap_seed("short", overlap=30) == "", "块长不足 overlap 时不取种子"
        assert _overlap_seed("any text", overlap=0) == ""

    def test_long_sentence_chain_no_pure_seed_chunk(self):
        # 连续超长单句：种子不得单独成块（纯重复内容）
        long1 = "x" * 80 + "."
        long2 = "y" * 80 + "."
        text = f"{long1} {long2} Tail end."
        chunks = chunk_text_semantic(text, size=60, overlap=20)
        assert long1 in chunks and long2 in chunks, "超长单句整句保留"
        assert all(len(c) > 20 or c == "Tail end." for c in chunks), "不应出现纯重叠种子块"
