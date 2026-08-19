"""RAG 真向量检索测试（32_rag_vector_retrieval_design.md §5）

- VectorStore：mock embedding upsert/search、可用性探测（callable/hash/无模型降级）
- search_hybrid 融合：词袋与向量得分矛盾（同义词命中）→ 取回语义片段；alpha=0 等价纯词袋
- 语义 chunk：标题/句子边界对齐，无句中截断
- Retriever strategy：hybrid 命中而 lexical 缺失
"""
from __future__ import annotations

import hashlib
import re

import numpy as np
import pytest
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.knowledge_base.competitor_store import CompetitorStore, TextChunk
from competitor_agent.knowledge_base.ingester import Ingester, chunk_text_semantic
from competitor_agent.knowledge_base.retriever import Retriever
from competitor_agent.knowledge_base.vector_store import VectorStore, VectorStoreUnavailableError, hash_embed

# chromadb 依赖：本环境已装；若 CI 环境缺失则整体 skip（不卡无依赖环境）
try:  # pragma: no cover
    import chromadb  # noqa: F401

    _HAS_CHROMADB = True
except Exception:  # noqa: BLE001 - chromadb 缺失则整体跳过 # pragma: no cover
    _HAS_CHROMADB = False

pytestmark = pytest.mark.skipif(not _HAS_CHROMADB, reason="chromadb 未安装，向量层不可用")


class _IdentityEmbedder:
    """确定性 mock 嵌入：含 'price' 的文本映射到 [1,0]，否则 [0,1]。"""

    def __call__(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "price" in t else [0.0, 1.0] for t in texts]


class _SynonymEmbedder:
    """语义 mock 嵌入：cost/pricing/price 归一到同一伪词，向量空间同义相似、词袋互异。"""

    _TOKEN_RE = re.compile(r"[a-z0-9]+")

    def __init__(self) -> None:
        self._dim = 64

    def __call__(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = np.zeros(self._dim)
            for tok in self._TOKEN_RE.findall(text.lower()):
                canon = {"cost": "price", "pricing": "price"}.get(tok, tok)
                idx = int(hashlib.sha256(canon.encode()).hexdigest(), 16) % self._dim
                v[idx] += 1.0
            norm = np.linalg.norm(v)
            out.append((v / norm).tolist() if norm else [0.0] * self._dim)
        return out


# ── 1. VectorStore（设计文档 32 §5 单测） ────────────────────────────────


class TestVectorStore:
    def test_mock_embed_upsert_search(self):
        vs = VectorStore(embed_fn=_IdentityEmbedder())
        vs.upsert(
            ["a", "b"],
            [[1.0, 0.0], [0.0, 1.0]],
            [{"competitor": "x", "dimension": "pricing"}, {"competitor": "x", "dimension": "feature"}],
        )
        hits = vs.search([1.0, 0.0], top_k=2)
        assert len(hits) == 2
        assert hits[0][0] == "a", "余弦相似应排 'price' 片段第一"
        assert hits[0][1] < hits[1][1], "distance 越小越相似"
        assert vs.count() == 2
        vs.clear()
        assert vs.count() == 0

    def test_callable_and_hash_available(self):
        assert VectorStore(embed_fn=_IdentityEmbedder()).is_available()
        assert VectorStore(embed_fn="hash").is_available()

    def test_unavailable_without_model(self, monkeypatch):
        import competitor_agent.knowledge_base.vector_store as vs_mod

        monkeypatch.setattr(vs_mod, "_semantic_embedder_cached", lambda name: False)
        vs = VectorStore(embed_fn=None)
        assert vs.is_available() is False
        with pytest.raises(VectorStoreUnavailableError):
            vs.embed(["x"])

    def test_hash_embed_deterministic(self):
        a = hash_embed(["hello world 你好", "hello world 你好"])
        assert a[0] == a[1], "哈希嵌入应确定性可复现"
        assert len(a[0]) == 256


# ── 2. search_hybrid 融合（设计文档 32 §5 融合单测） ─────────────────────


class TestSearchHybrid:
    def _store(self, tmp_path, embed_fn=None) -> CompetitorStore:
        return CompetitorStore(
            data_dir=tmp_path / "kb",
            vector_store=None if embed_fn is None else VectorStore(embed_fn=embed_fn),
        )

    def _seed(self, store: CompetitorStore) -> None:
        store.add(TextChunk("a", "cursor", "pricing", "subscription cost is $20", "https://c/pricing"))
        store.add(TextChunk("b", "cursor", "feature", "bananas are yellow fruit", "https://c/features"))

    def test_synonym_hits_hybrid_lexical_misses(self, tmp_path):
        store = self._store(tmp_path, embed_fn=_SynonymEmbedder())
        self._seed(store)
        hybrid = store.search_hybrid("price", top_k=3)
        assert hybrid and hybrid[0][0].chunk_id == "a", "hybrid 应经同义词命中 pricing 片段"
        assert hybrid[0][2] in ("fused", "vector")
        assert store.search("price", top_k=3) == [], "纯词袋查 price 命中不了 cost 片段"

    def test_alpha_zero_equals_pure_lexical(self, tmp_path):
        store = self._store(tmp_path, embed_fn=_SynonymEmbedder())
        self._seed(store)
        hybrid = store.search_hybrid("cost", top_k=3, alpha=0.0)
        lex = store.search("cost", top_k=3)
        assert [c.chunk_id for c, _, _ in hybrid] == [c.chunk_id for c, _ in lex]

    def test_alpha_one_equals_pure_vector(self, tmp_path):
        store = self._store(tmp_path, embed_fn=_SynonymEmbedder())
        self._seed(store)
        hybrid = store.search_hybrid("price", top_k=3, alpha=1.0)
        assert hybrid and hybrid[0][0].chunk_id == "a"

    def test_degrades_to_lexical_without_vector(self, tmp_path):
        store = self._store(tmp_path)
        self._seed(store)
        hits = store.search_hybrid("pricing", top_k=3)
        assert hits, "无向量层应降级词袋仍有结果"
        assert all(src == "lexical" for _, _, src in hits)


# ── 3. 语义 chunk（设计文档 32 §3.4 / §5） ──────────────────────────────


class TestChunkSemantic:
    def test_heading_and_sentence_boundary_no_mid_sentence_cut(self):
        doc = (
            "## Pricing Pro is $20 per month. Team is $40 per month.\n\n"
            "## Features Cursor has an AI code editor. It supports many languages."
        )
        chunks = chunk_text_semantic(doc, size=60)
        assert len(chunks) >= 3, "超限应切分"
        # 每块都以句末结束（不从句中截断）
        assert all(c.endswith((".", "。", "!", "？", "；", ";")) for c in chunks)
        # 无内容丢失
        assert "".join(c for c in chunks).replace(" ", "") == doc.replace(" ", "").replace("\n", "")

    def test_short_text_returns_single_chunk(self):
        assert chunk_text_semantic("short text.") == ["short text."]

    def test_single_long_sentence_not_force_cut(self):
        long = "word " * 500
        chunks = chunk_text_semantic(long, size=100)
        assert chunks == [long.strip()], "超长单句整句保留，不硬切"


# ── 4. Retriever strategy + API 接线（设计文档 32 §3.3 / §4） ───────────


class TestRetrieverStrategy:
    def test_hybrid_hits_lexical_misses(self, tmp_path):
        vs = VectorStore(embed_fn=_SynonymEmbedder())
        store = CompetitorStore(data_dir=tmp_path / "kb", vector_store=vs)
        store.add(TextChunk("a", "cursor", "pricing", "subscription cost is $20", ""))
        store.add(TextChunk("b", "cursor", "feature", "bananas are yellow fruit", ""))
        retriever = Retriever(store=store)
        hybrid = retriever.retrieve("price", "cursor", dimension="pricing", top_k=2, strategy="hybrid")
        lexical = retriever.retrieve("price", "cursor", dimension="pricing", top_k=2, strategy="lexical")
        assert any("$20" in c.text for c in hybrid)
        assert not any("$20" in c.text for c in lexical)

    def test_ingester_semantic_flag(self, tmp_path):
        store = CompetitorStore(data_dir=tmp_path / "kb")
        Ingester(store=store).ingest(
            "cursor", "feature", "## Editor It is an AI editor. ## Chat It has a chat.",
            semantic=True, chunk_size=40,
        )
        chunks = store.all_chunks()
        assert chunks, "semantic 分块应正常入库"
        assert all(c.text.endswith((".", "。")) for c in chunks), "semantic 分块不应句中截断"
        assert "".join(c.text for c in chunks).replace(" ", "") == (
            "## Editor It is an AI editor. ## Chat It has a chat.".replace(" ", "")
        ), "无内容丢失"


class TestApiWiresVectorStore:
    def _capture_store(self, monkeypatch) -> dict:
        captured: dict = {}

        class FakeStore:
            def __init__(self, *args, **kwargs):
                captured["vector_store"] = kwargs.get("vector_store")

        monkeypatch.setattr("competitor_agent.knowledge_base.competitor_store.CompetitorStore", FakeStore)
        return captured

    def test_api_passes_injected_vector_store_into_store(self, monkeypatch):
        captured = self._capture_store(monkeypatch)
        vs = VectorStore(embed_fn="hash")
        CompetitorAnalysisAPI(extractor=None, use_llm=False, enable_rag=True, vector_store=vs)
        assert captured["vector_store"] is vs, "注入的向量层应挂到知识库上"

    def test_api_creates_default_vector_store(self, monkeypatch):
        captured = self._capture_store(monkeypatch)
        CompetitorAnalysisAPI(extractor=None, use_llm=False, enable_rag=True)
        assert captured["vector_store"] is not None, "未注入时应默认构造向量层（模型不可用时自动降级）"
