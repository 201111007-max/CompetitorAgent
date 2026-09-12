"""知识库存储（CompetitorStore）— 按竞品×维度索引文档片段

存储层设计：
- 内存 + 可选 JSON 持久化（data_dir/knowledge_base.json）
- 每个文档片段带 competitor、dimension、text、chunk_id
- 向量库（chromadb）可选：安装 `rag` 依赖后自动使用，否则降级纯文本词袋
"""

from __future__ import annotations

import logging
import math
import threading
import time
from pathlib import Path
from typing import Any, Callable

from competitor_agent.domain_types.text_utils import tokenize
from competitor_agent.knowledge_base.vector_store import VectorStore, VectorStoreUnavailableError
from competitor_agent.memory.json_store import JsonStore

logger = logging.getLogger("competitor_agent.knowledge_base.competitor_store")

# \u65f6\u6548\u8870\u51cf\u534a\u8870\u671f\uff08\u5929\uff09\uff1a\u8bbe\u8ba1\u6587\u6863 93 \u51b3\u7b56 2\u2014\u2014\u7ade\u54c1\u4e8b\u5b9e"\u8fd1\u51b5\u4f18\u5148"\uff0c30 \u5929\u534a\u6743
_HALF_LIFE_DAYS = 30.0
_SECONDS_PER_DAY = 86400.0

__all__ = ["CompetitorStore", "TextChunk", "chunk_text", "tokenize"]


class TextChunk:
    """一条可检索的文档片段

    ingested_at：摄取时间戳（epoch 秒，设计文档 93 决策 3）；<=0 表示无时间戳，
    检索不衰减（直接构造未打戳的片段行为与旧版一致）。
    """

    __slots__ = ("chunk_id", "competitor", "dimension", "ingested_at", "source_url", "text")

    def __init__(
        self,
        chunk_id: str,
        competitor: str,
        dimension: str,
        text: str,
        source_url: str = "",
        ingested_at: float = 0.0,
    ) -> None:
        self.chunk_id = chunk_id
        self.competitor = competitor
        self.dimension = dimension
        self.text = text
        self.source_url = source_url
        self.ingested_at = float(ingested_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "competitor": self.competitor,
            "dimension": self.dimension,
            "text": self.text,
            "source_url": self.source_url,
            "ingested_at": self.ingested_at,
        }


def chunk_text(text: str, size: int = 1200, overlap: int = 200) -> list[str]:
    """把长文本按窗口切分成可检索片段"""
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


class CompetitorStore:
    """竞品文档知识库（词袋倒排索引）"""

    def __init__(
        self,
        data_dir: Path | str | None = None,
        vector_store: VectorStore | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self._store = JsonStore("knowledge_base", data_dir)
        self._chunks: list[TextChunk] = []
        self._idf: dict[str, float] = {}
        # 可选向量层（设计文档 32）：不可用时 search_hybrid 自动降级词袋
        self._vector_store = vector_store
        # 时钟可注入（设计文档 93 §2.1）：测试不依赖墙钟
        self._now_fn: Callable[[], float] = now_fn or time.time
        # RLock：并行缺口共享同一知识库（采集摄入 + 分析检索并发）
        self._lock = threading.RLock()
        self._load_chunks()

    # ---- 时效（设计文档 93 §2.1） ----
    def current_time(self) -> float:
        """注入时钟当前值（epoch 秒）；同批排序取同一时钟快照用。"""
        return float(self._now_fn())

    def decay_factor(self, chunk: TextChunk, now: float | None = None) -> float:
        """时效衰减因子：0.5 ** (age_days / 30)；无时间戳（ingested_at<=0）不衰减返回 1.0。"""
        ts = chunk.ingested_at
        if ts <= 0:
            return 1.0
        current = self._now_fn() if now is None else now
        age_days = max(0.0, (current - ts) / _SECONDS_PER_DAY)
        return 0.5 ** (age_days / _HALF_LIFE_DAYS)

    # ---- 写入 ----
    def add(self, chunk: TextChunk) -> None:
        self.add_many([chunk])

    def add_many(self, chunks: list[TextChunk]) -> None:
        with self._lock:
            by_id = {c.chunk_id: c for c in self._chunks}
            fresh: list[TextChunk] = []
            for chunk in chunks:
                existing = by_id.get(chunk.chunk_id)
                if existing is not None:
                    # 决策 4：重复摄取同一内容 = 刷新为最近确认（只更新时间戳，不重复追加）
                    if chunk.ingested_at > 0:
                        existing.ingested_at = chunk.ingested_at
                    continue
                by_id[chunk.chunk_id] = chunk
                fresh.append(chunk)
            self._chunks.extend(fresh)
            self._rebuild_index()
            self._persist()
            self._embed_chunks(fresh)

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()
            self._idf.clear()
            if self._vector_store is not None:
                self._vector_store.clear()
            self._store.clear()
            self._store.save()

    # ---- 读取 ----
    def all_chunks(self) -> list[TextChunk]:
        with self._lock:
            return list(self._chunks)

    def by_competitor(self, competitor: str) -> list[TextChunk]:
        with self._lock:
            return [c for c in self._chunks if c.competitor == competitor]

    def by_dimension(self, dimension: str) -> list[TextChunk]:
        with self._lock:
            return [c for c in self._chunks if c.dimension == dimension]

    def search(self, query: str, top_k: int = 5) -> list[tuple[TextChunk, float]]:
        """词袋余弦检索（查询词命中率加权）"""
        with self._lock:
            if not self._chunks:
                return []
            q_tokens = tokenize(query)
            if not q_tokens:
                return []
            q_weights = _term_weights(q_tokens, self._idf)
            now = self._now_fn()
            scored: list[tuple[TextChunk, float]] = []
            for chunk in self._chunks:
                c_tokens = tokenize(chunk.text)
                if not c_tokens:
                    continue
                c_weights = _term_weights(c_tokens, self._idf)
                score = _cosine(q_weights, c_weights)
                # 维度命中加权：查询含维度词时同维度片段加分
                for dim_token in tokenize(chunk.dimension):
                    if dim_token in q_tokens:
                        score += 0.15
                # 时效衰减（设计文档 93 §2.1）：0.5 ** (age_days / 30)
                score *= self.decay_factor(chunk, now)
                if score > 0:
                    scored.append((chunk, score))
            scored.sort(key=lambda kv: kv[1], reverse=True)
            return scored[:top_k]

    def search_hybrid(
        self, query: str, top_k: int = 5, alpha: float = 0.5
    ) -> list[tuple[TextChunk, float, str]]:
        """词袋 + 向量归一化后加权融合（设计文档 32）。

        alpha = 向量权重（0 等价纯词袋，1 纯向量）；返回 (chunk, fused_score, source)，
        source ∈ {"lexical", "vector", "fused"}。向量层不可用时等价 search。
        """
        with self._lock:
            lexical = self.search(query, top_k=top_k * 2)
            vs = self._vector_store
            if vs is None or not vs.is_available():
                return [(c, s, "lexical") for c, s in lexical[:top_k]]
            try:
                query_vec = vs.embed([query])[0]
                vector_hits = vs.search(query_vec, top_k=top_k * 2)
            except VectorStoreUnavailableError:
                return [(c, s, "lexical") for c, s in lexical[:top_k]]

            by_id = {c.chunk_id: c for c in self._chunks}
            vector_hits = [(cid, d) for cid, d in vector_hits if cid in by_id]
            if not vector_hits:
                return [(c, s, "lexical") for c, s in lexical[:top_k]]

            # 各自 min-max 归一化到 [0,1]（向量距离 → 相似度 1/(1+d)）
            lex_map = _minmax({c.chunk_id: s for c, s in lexical})
            vec_map = _minmax({cid: 1.0 / (1.0 + d) for cid, d in vector_hits})

            merged: list[tuple[TextChunk, float, str]] = []
            now = self._now_fn()
            for cid in set(lex_map) | set(vec_map):
                chunk = by_id[cid]
                lv = lex_map.get(cid, 0.0)
                vv = vec_map.get(cid, 0.0)
                # 时效衰减（设计文档 93 §2.1）：融合分乘 0.5 ** (age_days / 30)
                fused = ((1.0 - alpha) * lv + alpha * vv) * self.decay_factor(chunk, now)
                source = (
                    "fused"
                    if (cid in lex_map and cid in vec_map)
                    else ("lexical" if cid in lex_map else "vector")
                )
                if fused > 0:
                    merged.append((chunk, fused, source))
            merged.sort(key=lambda kv: kv[1], reverse=True)
            return merged[:top_k]

    # ---- 内部 ----
    def _load_chunks(self) -> None:
        raw = self._store.get("chunks", [])
        if not isinstance(raw, list):
            return
        migrated = False
        for item in raw:
            if isinstance(item, dict):
                # 迁移语义（设计文档 93 §2.1）：旧 JSON 无 ingested_at 字段 →
                # 置为迁移时刻（首次以新版本加载的时间），随后按自然老化
                if "ingested_at" in item:
                    ts = float(item.get("ingested_at") or 0.0)
                else:
                    ts = float(self._now_fn())
                    migrated = True
                self._chunks.append(
                    TextChunk(
                        chunk_id=str(item.get("chunk_id", "")),
                        competitor=str(item.get("competitor", "")),
                        dimension=str(item.get("dimension", "")),
                        text=str(item.get("text", "")),
                        source_url=str(item.get("source_url", "")),
                        ingested_at=ts,
                    )
                )
        self._rebuild_index()
        if migrated:
            self._persist()  # 迁移只发生一次：时间戳落盘后后续加载走正常字段
        # 从 JSON 重载后若有可用向量层则重建向量索引（哈希/mock 嵌入确定性可复现）
        self._embed_chunks(self._chunks)

    def _persist(self) -> None:
        self._store.put("chunks", [c.to_dict() for c in self._chunks])
        self._store.save()

    def _embed_chunks(self, chunks: list[TextChunk]) -> None:
        """向量层可用时对新增片段增量生成嵌入并 upsert（不可用/失败静默降级）。

        跳过已在集合中的 chunk_id 并去重——历史知识库 JSON 可能含重复 id（同内容重复摄入），
        直接 upsert 会触发 chromadb DuplicateIDError。
        """
        vs = self._vector_store
        if vs is None or not chunks or not vs.is_available():
            return
        existing = vs.get_existing([c.chunk_id for c in chunks])
        seen: set[str] = set()
        fresh: list[TextChunk] = []
        for chunk in chunks:
            if chunk.chunk_id in seen or chunk.chunk_id in existing:
                continue
            seen.add(chunk.chunk_id)
            fresh.append(chunk)
        if not fresh:
            return
        try:
            vectors = vs.embed([c.text for c in fresh])
        except VectorStoreUnavailableError:
            return
        vs.upsert(
            [c.chunk_id for c in fresh],
            vectors,
            [
                {
                    "competitor": c.competitor,
                    "dimension": c.dimension,
                    "source_url": c.source_url,
                    "ingested_at": c.ingested_at,
                }
                for c in fresh
            ],
        )

    def _rebuild_index(self) -> None:
        df: dict[str, int] = {}
        for chunk in self._chunks:
            for token in set(tokenize(chunk.text)):
                df[token] = df.get(token, 0) + 1
        n = max(len(self._chunks), 1)
        self._idf = {t: math.log((n + 1.0) / (c + 1.0)) + 1.0 for t, c in df.items()}


def _term_weights(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    """TF * IDF 权重"""
    tf: dict[str, int] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    total = max(len(tokens), 1)
    return {t: (c / total) * idf.get(t, 1.0) for t, c in tf.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(av * b.get(t, 0.0) for t, av in a.items())
    na = math.sqrt(sum(v * v for v in a.values())) or 1.0
    nb = math.sqrt(sum(v * v for v in b.values())) or 1.0
    return dot / (na * nb)


def _minmax(scores: dict[str, float]) -> dict[str, float]:
    """min-max 归一化到 [0,1]；单元素返回 1.0，空返回空。"""
    if not scores:
        return {}
    lo = min(scores.values())
    hi = max(scores.values())
    span = hi - lo
    if span <= 0:
        return {k: 1.0 for k in scores}
    return {k: (v - lo) / span for k, v in scores.items()}
