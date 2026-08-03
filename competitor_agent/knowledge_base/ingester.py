"""知识库摄取（Ingester）— 文档 → 分块 → 入库

接收竞品文档/Changelog 原始文本，按竞品×维度切块写入 CompetitorStore。
"""
from __future__ import annotations

import hashlib
from typing import Any

from competitor_agent.knowledge_base.competitor_store import CompetitorStore, TextChunk, chunk_text


class Ingester:
    """文档摄取器"""

    def __init__(self, store: CompetitorStore) -> None:
        self._store = store

    def ingest(
        self,
        competitor: str,
        dimension: str,
        text: str,
        source_url: str = "",
        chunk_size: int = 1200,
        overlap: int = 200,
    ) -> int:
        """摄取一段文档，返回生成的片段数"""
        if not text.strip():
            return 0
        chunks = chunk_text(text, size=chunk_size, overlap=overlap)
        items = []
        for i, part in enumerate(chunks):
            chunk_id = _chunk_id(competitor, dimension, part)
            items.append(
                TextChunk(
                    chunk_id=chunk_id,
                    competitor=competitor,
                    dimension=dimension,
                    text=part,
                    source_url=source_url,
                )
            )
        self._store.add_many(items)
        return len(items)

    def ingest_document(self, competitor: str, document: dict[str, Any]) -> int:
        """摄取一个结构化文档：{dimension: text, ...}"""
        total = 0
        for dimension, text in document.items():
            total += self.ingest(competitor, dimension, str(text))
        return total


def _chunk_id(competitor: str, dimension: str, text: str) -> str:
    digest = hashlib.sha256(f"{competitor}:{dimension}:{text}".encode()).hexdigest()[:16]
    return f"{competitor}:{dimension}:{digest}"