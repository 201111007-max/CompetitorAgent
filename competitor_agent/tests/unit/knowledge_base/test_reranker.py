"""bge-reranker 精排测试（93_rag_deepening_design.md §2.2 / §3）

- is_available 无本地权重 → False 且不触网（mock 缓存探测）
- 注入 stub CrossEncoder → 精排改变顺序
- reranker 不可用 / 打分失败 → 与现状路径逐位一致（回归安全阀）
- lexical 策略不经精排（消融路径不变）
- facade 注入接线（与 vector_store 注入同风格）
"""

from __future__ import annotations

import competitor_agent.knowledge_base.reranker as reranker_mod
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.knowledge_base.competitor_store import CompetitorStore, TextChunk
from competitor_agent.knowledge_base.reranker import CrossEncoderReranker
from competitor_agent.knowledge_base.retriever import Retriever

_T0 = 1_800_000_000.0


class _StubCrossEncoder:
    """确定性 stub：含 'banana' 的文本给高分（反转词袋排序），记录调用。"""

    def __init__(self) -> None:
        self.calls = 0

    def predict(self, pairs):
        self.calls += 1
        return [1.0 if "banana" in text else 0.0 for _q, text in pairs]


class _ExplodingCrossEncoder:
    def predict(self, pairs):
        raise RuntimeError("boom")


def _seeded_store(tmp_path) -> CompetitorStore:
    store = CompetitorStore(data_dir=tmp_path / "kb")
    # 词袋下 "price" 查询命中 a；b 不含 price 相关词，词袋分低
    store.add(TextChunk("a", "cursor", "pricing", "price price price subscription cost", ingested_at=_T0))
    store.add(TextChunk("b", "cursor", "feature", "banana smoothie recipe price", ingested_at=_T0))
    return store


class TestAvailability:
    def test_unavailable_without_cached_weights(self, monkeypatch):
        monkeypatch.setattr(reranker_mod, "_cached_weight_path", lambda name: None)
        reranker = CrossEncoderReranker()
        assert reranker.is_available() is False, "无本地权重应不可用"
        assert reranker.rerank("q", [TextChunk("a", "c", "d", "t")]) is None, "不可用应返回 None 走降级"

    def test_available_with_cached_weights_but_load_failure_marks_unavailable(self, monkeypatch):
        import sys
        import types

        monkeypatch.setattr(reranker_mod, "_cached_weight_path", lambda name: "/tmp/fake.bin")

        # 假 sentence_transformers 模块：构造即失败——保证测试离线且不依赖本机依赖装态
        def _boom(name):
            raise RuntimeError("load fail")

        monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(CrossEncoder=_boom))
        reranker = CrossEncoderReranker()
        assert reranker.is_available() is True
        # 权重"存在"但加载失败：标记不可用，rerank 返回 None
        assert reranker.rerank("q", [TextChunk("a", "c", "d", "t")]) is None
        assert reranker.is_available() is False

    def test_injected_stub_always_available(self):
        reranker = CrossEncoderReranker(cross_encoder=_StubCrossEncoder())
        assert reranker.is_available() is True


class TestRerank:
    def test_rerank_changes_order(self):
        stub = _StubCrossEncoder()
        reranker = CrossEncoderReranker(cross_encoder=stub)
        chunks = [
            TextChunk("a", "cursor", "pricing", "full price list"),
            TextChunk("b", "cursor", "feature", "banana feature"),
        ]
        out = reranker.rerank("pricing", chunks, top_k=2)
        assert out is not None and stub.calls == 1
        assert out[0][0].chunk_id == "b", "stub 给 banana 高分，精排应反转顺序"
        assert out[0][1] > out[1][1]

    def test_scoring_failure_returns_none(self):
        reranker = CrossEncoderReranker(cross_encoder=_ExplodingCrossEncoder())
        out = reranker.rerank("q", [TextChunk("a", "c", "d", "t")])
        assert out is None, "打分异常应返回 None（调用方降级）"


class TestRetrieverWiring:
    def test_reranker_flips_retrieve_order(self, tmp_path):
        store = _seeded_store(tmp_path)
        baseline = Retriever(store).retrieve("price", "cursor", top_k=2)
        assert baseline[0].chunk_id == "a", "基线：词袋高分片段在前"
        reranked = Retriever(
            store, reranker=CrossEncoderReranker(cross_encoder=_StubCrossEncoder())
        ).retrieve("price", "cursor", top_k=2)
        assert reranked[0].chunk_id == "b", "精排后 stub 高分片段应排前"

    def test_unavailable_reranker_bit_identical(self, tmp_path, monkeypatch):
        monkeypatch.setattr(reranker_mod, "_cached_weight_path", lambda name: None)
        store = _seeded_store(tmp_path)
        baseline = Retriever(store).retrieve("price", "cursor", top_k=2)
        degraded = Retriever(store, reranker=CrossEncoderReranker()).retrieve("price", "cursor", top_k=2)
        assert [c.chunk_id for c in baseline] == [c.chunk_id for c in degraded], (
            "reranker 不可用时应与现状路径逐位一致"
        )

    def test_scoring_failure_falls_back_to_hybrid(self, tmp_path):
        store = _seeded_store(tmp_path)
        baseline = Retriever(store).retrieve("price", "cursor", top_k=2)
        degraded = Retriever(
            store, reranker=CrossEncoderReranker(cross_encoder=_ExplodingCrossEncoder())
        ).retrieve("price", "cursor", top_k=2)
        assert [c.chunk_id for c in baseline] == [c.chunk_id for c in degraded]

    def test_lexical_strategy_bypasses_reranker(self, tmp_path):
        store = _seeded_store(tmp_path)
        stub = _StubCrossEncoder()
        hits = Retriever(store, reranker=CrossEncoderReranker(cross_encoder=stub)).retrieve(
            "price", "cursor", top_k=2, strategy="lexical"
        )
        assert stub.calls == 0, "lexical 消融路径不应触发精排"
        assert hits[0].chunk_id == "a"


class TestApiWiresReranker:
    def test_api_uses_injected_reranker(self, monkeypatch):
        monkeypatch.setattr(reranker_mod, "_cached_weight_path", lambda name: None)
        reranker = CrossEncoderReranker(cross_encoder=_StubCrossEncoder())
        api = CompetitorAnalysisAPI(extractor=None, use_llm=False, enable_rag=True, reranker=reranker)
        assert api._reranker is reranker

    def test_api_default_probe_degrades_without_weights(self, monkeypatch):
        monkeypatch.setattr(reranker_mod, "_cached_weight_path", lambda name: None)
        api = CompetitorAnalysisAPI(extractor=None, use_llm=False, enable_rag=True)
        assert api._reranker is None, "权重未缓存时默认构造应降级为 None（hybrid 直出）"

    def test_api_no_reranker_when_rag_disabled(self):
        api = CompetitorAnalysisAPI(extractor=None, use_llm=False, enable_rag=False)
        assert api._reranker is None
        assert api._retriever is None
