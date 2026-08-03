"""知识库存储（CompetitorStore）— 按竞品×维度索引文档片段

存储层设计：
- 内存 + 可选 JSON 持久化（data_dir/knowledge_base.json）
- 每个文档片段带 competitor、dimension、text、chunk_id
- 向量库（chromadb）可选：安装 `rag` 依赖后自动使用，否则降级纯文本词袋
"""
from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Any

from competitor_agent.memory.json_store import JsonStore

logger = logging.getLogger("competitor_agent.knowledge_base.competitor_store")

_WORD_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]+")


class TextChunk:
    """一条可检索的文档片段"""

    __slots__ = ("chunk_id", "competitor", "dimension", "source_url", "text")

    def __init__(self, chunk_id: str, competitor: str, dimension: str, text: str, source_url: str = "") -> None:
        self.chunk_id = chunk_id
        self.competitor = competitor
        self.dimension = dimension
        self.text = text
        self.source_url = source_url

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "competitor": self.competitor,
            "dimension": self.dimension,
            "text": self.text,
            "source_url": self.source_url,
        }


def tokenize(text: str) -> list[str]:
    """中英文通用分词（小写 + 词元）"""
    return _WORD_RE.findall(text.lower())


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

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self._store = JsonStore("knowledge_base", data_dir)
        self._chunks: list[TextChunk] = []
        self._idf: dict[str, float] = {}
        self._load_chunks()

    # ---- 写入 ----
    def add(self, chunk: TextChunk) -> None:
        self._chunks.append(chunk)
        self._rebuild_index()
        self._persist()

    def add_many(self, chunks: list[TextChunk]) -> None:
        self._chunks.extend(chunks)
        self._rebuild_index()
        self._persist()

    def clear(self) -> None:
        self._chunks.clear()
        self._idf.clear()
        self._store.clear()
        self._store.save()

    # ---- 读取 ----
    def all_chunks(self) -> list[TextChunk]:
        return list(self._chunks)

    def by_competitor(self, competitor: str) -> list[TextChunk]:
        return [c for c in self._chunks if c.competitor == competitor]

    def by_dimension(self, dimension: str) -> list[TextChunk]:
        return [c for c in self._chunks if c.dimension == dimension]

    def search(self, query: str, top_k: int = 5) -> list[tuple[TextChunk, float]]:
        """词袋余弦检索（查询词命中率加权）"""
        if not self._chunks:
            return []
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        q_weights = _term_weights(q_tokens, self._idf)
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
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda kv: kv[1], reverse=True)
        return scored[:top_k]

    # ---- 内部 ----
    def _load_chunks(self) -> None:
        raw = self._store.get("chunks", [])
        if not isinstance(raw, list):
            return
        for item in raw:
            if isinstance(item, dict):
                self._chunks.append(
                    TextChunk(
                        chunk_id=str(item.get("chunk_id", "")),
                        competitor=str(item.get("competitor", "")),
                        dimension=str(item.get("dimension", "")),
                        text=str(item.get("text", "")),
                        source_url=str(item.get("source_url", "")),
                    )
                )
        self._rebuild_index()

    def _persist(self) -> None:
        self._store.put("chunks", [c.to_dict() for c in self._chunks])
        self._store.save()

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