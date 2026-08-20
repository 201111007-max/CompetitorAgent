"""retrieval_compare 检索质量对照单测（设计文档 52 §2.3 / M3）

- 固定查询集提炼：语料/去重/相关标注（同竞品×维度）
- 三模式 recall@k：hash 嵌入确定性、零网络；向量/混合模式在 chromadb 缺失时记 n/a
- 对比表渲染与落盘；main() 出口码与输出
"""
from __future__ import annotations

import pytest
from competitor_agent.evaluation import retrieval_compare as rc
from competitor_agent.evaluation.retrieval_compare import (
    CompareResult,
    ModeResult,
    RetrievalCase,
    load_cases,
    main,
    render_compare_table,
    run_compare,
    write_compare_report,
)
from competitor_agent.knowledge_base import vector_store as vs_mod
from competitor_agent.knowledge_base.competitor_store import TextChunk

try:  # pragma: no cover
    import chromadb  # noqa: F401

    _HAS_CHROMADB = True
except Exception:  # noqa: BLE001 - chromadb 缺失时跳过向量模式断言 # pragma: no cover
    _HAS_CHROMADB = False

requires_chromadb = pytest.mark.skipif(not _HAS_CHROMADB, reason="chromadb 未安装")


def _synthetic() -> tuple[list[TextChunk], list[RetrievalCase]]:
    chunks = [
        TextChunk("c1", "acme", "pricing", "定价 方案"),
        TextChunk("c2", "acme", "pricing", "免费版 功能受限"),
        TextChunk("c3", "acme", "performance", "基准 跑分 延迟 吞吐"),
        TextChunk("c4", "globex", "pricing", "订阅 席位 计费"),
    ]
    # q1 三词各命中 c1/c2/c4：c4 词袋得分最低被 min-max 归零（search_hybrid 既有语义），
    # 相关的 c1/c2 同分并列保留 → recall 1.0
    cases = [
        RetrievalCase("q1", "定价 免费版 订阅", "acme", "pricing", ["c1", "c2"]),
        RetrievalCase("q2", "acme 性能 基准", "acme", "performance", ["c3"]),
    ]
    return chunks, cases


class TestLoadCases:
    def test_corpus_and_query_set(self):
        chunks, cases = load_cases()
        assert len(chunks) == 27
        assert len(cases) == 18  # 按 (task, competitor, dimension) 去重后 ~20 条
        for case in cases:
            assert case.relevant_ids
            for cid in case.relevant_ids:
                chunk = next(c for c in chunks if c.chunk_id == cid)
                assert chunk.competitor == case.competitor
                assert chunk.dimension == case.dimension

    def test_dedupe_same_task(self):
        _, cases = load_cases()
        keys = [(c.query, c.competitor, c.dimension) for c in cases]
        assert len(keys) == len(set(keys))
        cursor_pricing = [c for c in cases if c.competitor == "cursor" and c.dimension == "pricing"]
        assert len(cursor_pricing) == 1
        # cursor×pricing 的 3 个 fixture case 全部标注为相关条目
        assert len(cursor_pricing[0].relevant_ids) == 3


@requires_chromadb
class TestRunCompare:
    def test_three_modes_in_bounds(self):
        chunks, cases = load_cases()
        result = run_compare(chunks, cases, embed_fn="hash")
        assert [m.mode for m in result.modes] == ["lexical", "vector", "hybrid"]
        assert result.n_chunks == 27
        assert result.embed_label == "hash"
        for m in result.modes:
            assert m.available
            assert set(m.per_case) == {c.case_id for c in cases}
            for v in m.per_case.values():
                assert 0.0 <= v <= 1.0
            assert m.mean is not None and 0.0 <= m.mean <= 1.0

    def test_deterministic_with_hash(self):
        chunks, cases = load_cases()
        r1 = run_compare(chunks, cases, embed_fn="hash")
        r2 = run_compare(chunks, cases, embed_fn="hash")
        for m1, m2 in zip(r1.modes, r2.modes):
            assert m1.per_case == m2.per_case

    def test_lexical_hits_exact_terms(self):
        """词面完全覆盖的查询：纯词袋（alpha=0）应召回全部相关条目。"""
        chunks, cases = _synthetic()
        result = run_compare(chunks, cases, embed_fn="hash")
        lexical = result.modes[0]
        assert lexical.mode == "lexical"
        assert lexical.per_case["q1"] == 1.0
        assert lexical.per_case["q2"] == 1.0

    def test_chromadb_missing_marks_na(self, monkeypatch):
        """chromadb 不可用：向量/混合模式 n/a，纯词袋照常（默认安装环境可跑）。"""
        monkeypatch.setattr(rc, "_chromadb_available", lambda: False)
        chunks, cases = _synthetic()
        result = run_compare(chunks, cases, embed_fn="hash")
        lexical, vector, hybrid = result.modes
        assert lexical.available and lexical.per_case["q1"] == 1.0
        assert not vector.available and vector.mean is None
        assert not hybrid.available and hybrid.mean is None

    def test_uncached_model_marks_na(self, monkeypatch):
        """--embed auto 且模型未缓存：向量/混合 n/a 而非静默退成词袋数据。"""
        monkeypatch.setattr(vs_mod, "_semantic_embedder_cached", lambda name: False)
        chunks, cases = _synthetic()
        result = run_compare(chunks, cases, embed_fn=None)
        assert not result.modes[1].available
        assert not result.modes[2].available


class TestRenderTable:
    def _result(self, available: bool = True) -> CompareResult:
        cases = [RetrievalCase("q1", "acme 定价", "acme", "pricing", ["c1", "c2"])]
        modes = [
            ModeResult("lexical", 0.0, {"q1": 0.5}),
            ModeResult("vector", 1.0, {"q1": 1.0} if available else {}, available=available),
            ModeResult("hybrid", 0.5, {"q1": 1.0} if available else {}, available=available),
        ]
        return CompareResult(top_k=5, embed_label="hash", n_chunks=2, cases=cases, modes=modes)

    def test_table_structure(self):
        md = render_compare_table(self._result())
        assert "lexical recall" in md and "vector recall" in md and "hybrid recall" in md
        assert "embed: hash" in md and "recall@5" in md
        assert "| q1 | acme×pricing | 2 | 0.50 | 1.00 | 1.00 |" in md
        # 均值行最优加粗
        assert "**1.0000**" in md

    def test_unavailable_mode_renders_na(self):
        md = render_compare_table(self._result(available=False))
        assert "| q1 | acme×pricing | 2 | 0.50 | n/a | n/a |" in md


class TestWriteAndMain:
    def test_write_report(self, tmp_path):
        _, cases = _synthetic()
        result = CompareResult(
            top_k=5,
            embed_label="hash",
            n_chunks=4,
            cases=cases,
            modes=[ModeResult("lexical", 0.0, {"q1": 1.0, "q2": 1.0})],
        )
        path = write_compare_report(result, tmp_path / "reports")
        assert path.name.startswith("retrieval_compare_") and path.suffix == ".md"
        assert path.read_text(encoding="utf-8") == render_compare_table(result)

    @requires_chromadb
    def test_main_hash_exit_0(self, tmp_path, capsys):
        code = main(["--embed", "hash", "--out", str(tmp_path)])
        out = capsys.readouterr().out
        assert code == 0
        assert "查询集: 18 条" in out
        assert "lexical" in out and "hybrid" in out
        assert list(tmp_path.glob("retrieval_compare_*.md"))

    def test_main_embed_auto_without_cache(self, tmp_path, monkeypatch, capsys):
        """--embed auto 无模型缓存：向量/混合 n/a，仍正常出表退出 0（零网络）。"""
        monkeypatch.setattr(vs_mod, "_semantic_embedder_cached", lambda name: False)
        code = main(["--embed", "auto", "--out", str(tmp_path)])
        out = capsys.readouterr().out
        assert code == 0
        assert "n/a" in out
