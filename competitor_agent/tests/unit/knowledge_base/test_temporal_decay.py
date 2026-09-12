"""时效衰减测试（93_rag_deepening_design.md §2.1 / §3）

- now_fn 注入：同龄同分、30 天半权、60 天 1/4 权（不依赖墙钟）
- 重复摄取同一内容 = 刷新为最近确认（决策 4：更新时间戳，不重复追加）
- 旧 knowledge_base.json 无 ingested_at 字段 → 载入置迁移时刻
- 无时间戳片段不衰减（直接构造未打戳 → 因子 1.0，行为与旧版一致）
- retrieve_by_dimension 衰减排序一致；vector_store metadata 同步带 ingested_at
"""

from __future__ import annotations

import json

from competitor_agent.knowledge_base.competitor_store import CompetitorStore, TextChunk
from competitor_agent.knowledge_base.ingester import Ingester
from competitor_agent.knowledge_base.retriever import Retriever

_DAY = 86400.0
_T0 = 1_800_000_000.0  # 固定纪元锚点，与墙钟无关


class _Clock:
    def __init__(self, t: float = _T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _store(tmp_path, clock: _Clock) -> CompetitorStore:
    return CompetitorStore(data_dir=tmp_path / "kb", now_fn=clock)


class TestDecayFactor:
    def test_no_timestamp_no_decay(self, tmp_path):
        clock = _Clock()
        store = _store(tmp_path, clock)
        chunk = TextChunk("a", "cursor", "pricing", "cursor pricing info")
        assert store.decay_factor(chunk) == 1.0, "无时间戳片段不衰减"
        clock.t += 365 * _DAY
        assert store.decay_factor(chunk) == 1.0, "时间推移后仍不衰减"

    def test_half_life_30_days(self, tmp_path):
        clock = _Clock()
        store = _store(tmp_path, clock)
        chunk = TextChunk("a", "cursor", "pricing", "text", ingested_at=_T0)
        assert store.decay_factor(chunk) == 1.0
        clock.t = _T0 + 30 * _DAY
        assert abs(store.decay_factor(chunk) - 0.5) < 1e-9, "30 天半权"
        clock.t = _T0 + 60 * _DAY
        assert abs(store.decay_factor(chunk) - 0.25) < 1e-9, "60 天 1/4 权"


class TestSearchDecay:
    def test_same_age_same_score(self, tmp_path):
        clock = _Clock()
        store = _store(tmp_path, clock)
        store.add(TextChunk("a", "cursor", "pricing", "cursor pro price info", ingested_at=_T0))
        store.add(TextChunk("b", "cursor", "pricing", "cursor pro price info", ingested_at=_T0))
        hits = store.search("cursor pro price", top_k=2)
        assert len(hits) == 2
        assert abs(hits[0][1] - hits[1][1]) < 1e-12, "同龄同文应同分"

    def test_older_chunk_scores_lower(self, tmp_path):
        clock = _Clock(_T0 + 30 * _DAY)
        store = _store(tmp_path, clock)
        store.add(TextChunk("new", "cursor", "pricing", "cursor pro price info", ingested_at=_T0 + 30 * _DAY))
        store.add(TextChunk("old", "cursor", "pricing", "cursor pro price info", ingested_at=_T0))
        hits = store.search("cursor pro price", top_k=2)
        assert hits[0][0].chunk_id == "new", "同龄内容新片段应排前"
        assert abs(hits[0][1] / hits[1][1] - 2.0) < 1e-9, "30 天差异应为 2 倍分差"

    def test_hybrid_path_decays_without_vector(self, tmp_path):
        clock = _Clock(_T0 + 30 * _DAY)
        store = _store(tmp_path, clock)
        store.add(TextChunk("new", "cursor", "pricing", "cursor pro price info", ingested_at=_T0 + 30 * _DAY))
        store.add(TextChunk("old", "cursor", "pricing", "cursor pro price info", ingested_at=_T0))
        hits = store.search_hybrid("cursor pro price", top_k=2)
        assert hits[0][0].chunk_id == "new", "hybrid（无向量层降级词袋）同样衰减"
        assert all(src == "lexical" for _, _, src in hits)

    def test_retrieve_by_dimension_fresh_first(self, tmp_path):
        clock = _Clock(_T0 + 30 * _DAY)
        store = _store(tmp_path, clock)
        store.add(TextChunk("old", "cursor", "pricing", "old pricing", ingested_at=_T0))
        store.add(TextChunk("new", "cursor", "pricing", "new pricing", ingested_at=_T0 + 30 * _DAY))
        hits = Retriever(store).retrieve_by_dimension("cursor", "pricing")
        assert [c.chunk_id for c in hits] == ["new", "old"], "retrieve_by_dimension 衰减排序：新片段优先"


class TestIngestTimestamp:
    def test_ingest_stamps_now(self, tmp_path):
        clock = _Clock()
        store = _store(tmp_path, clock)
        Ingester(store, now_fn=clock).ingest("cursor", "pricing", "Cursor Pro is $20 per month.")
        chunks = store.all_chunks()
        assert chunks and all(c.ingested_at == _T0 for c in chunks), "ingest 应写入注入时钟时间戳"

    def test_reingest_refreshes_timestamp_no_duplicate(self, tmp_path):
        clock = _Clock()
        store = _store(tmp_path, clock)
        ingester = Ingester(store, now_fn=clock)
        ingester.ingest("cursor", "pricing", "Cursor Pro is $20 per month.")
        clock.t = _T0 + 40 * _DAY
        ingester.ingest("cursor", "pricing", "Cursor Pro is $20 per month.")
        chunks = store.all_chunks()
        assert len(chunks) == 1, "决策 4：同内容重复摄取不重复追加"
        assert chunks[0].ingested_at == _T0 + 40 * _DAY, "重复摄取应刷新为最近确认时间"
        # 刷新后不衰减：检索分与新鲜片段一致
        assert store.decay_factor(chunks[0]) == 1.0


class TestLegacyMigration:
    def test_legacy_json_without_timestamp_migrates(self, tmp_path):
        data_dir = tmp_path / "kb"
        store = CompetitorStore(data_dir=data_dir, now_fn=_Clock(_T0))
        store.add(TextChunk("a", "cursor", "pricing", "legacy pricing info", ingested_at=_T0))
        # 模拟旧版 JSON：抹掉 ingested_at 字段
        path = data_dir / "memory" / "knowledge_base.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        for item in raw["chunks"]:
            item.pop("ingested_at")
        path.write_text(json.dumps(raw), encoding="utf-8")
        store2 = CompetitorStore(data_dir=data_dir, now_fn=_Clock(_T0 + 10 * _DAY))
        chunks = store2.all_chunks()
        assert len(chunks) == 1
        assert chunks[0].ingested_at == _T0 + 10 * _DAY, "无时间戳旧数据应置迁移时刻"
        # 迁移只发生一次：落盘后再次加载走正常字段
        store3 = CompetitorStore(data_dir=data_dir, now_fn=_Clock(_T0 + 20 * _DAY))
        assert store3.all_chunks()[0].ingested_at == _T0 + 10 * _DAY


class _FakeVectorStore:
    """记录 upsert 的假向量层（验证 metadata 同步 ingested_at，不依赖 chromadb）。"""

    def __init__(self) -> None:
        self.metadatas: list[dict] = []

    def is_available(self) -> bool:
        return True

    def get_existing(self, chunk_ids):
        return set()

    def embed(self, texts):
        return [[1.0, 0.0]] * len(texts)

    def upsert(self, chunk_ids, vectors, metadatas):
        self.metadatas.extend(metadatas)


class TestVectorMetadataSync:
    def test_upsert_metadata_carries_ingested_at(self, tmp_path):
        vs = _FakeVectorStore()
        store = CompetitorStore(data_dir=tmp_path / "kb", vector_store=vs, now_fn=_Clock(_T0))
        store.add(TextChunk("a", "cursor", "pricing", "text", ingested_at=_T0))
        assert vs.metadatas and vs.metadatas[0]["ingested_at"] == _T0, (
            "vector_store metadata 应同步带 ingested_at"
        )
