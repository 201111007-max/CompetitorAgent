"""知识库摄取（Ingester）— 文档 → 分块 → 入库

接收竞品文档/Changelog 原始文本，按竞品×维度切块写入 CompetitorStore。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from competitor_agent.knowledge_base.competitor_store import CompetitorStore, TextChunk, chunk_text

# 句子结束符（中文/英文句号、感叹、问号、分号后断句）
_SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?.；;])\s*")


def _split_blocks(text: str) -> list[str]:
    """按空行 / Markdown 标题行切候选块，保留标题为独立块。"""
    blocks: list[str] = []
    cur: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if cur:
                blocks.append(" ".join(cur))
                cur = []
            if stripped:
                blocks.append(stripped)
        else:
            cur.append(stripped)
    if cur:
        blocks.append(" ".join(cur))
    return blocks


def chunk_text_semantic(text: str, size: int = 1200, overlap: int = 200) -> list[str]:
    """语义感知分块：先按标题/空行/句子边界切候选块，再折叠到 size 上限。

    与 ``chunk_text``（固定窗口硬切）不同，分块边界总是落在标题/段落/句末，
    减少从句中截断；极长单句（>size）整句保留不硬切。
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    sentences: list[str] = []
    for block in _split_blocks(text):
        sentences.extend(s for s in _SENT_SPLIT_RE.split(block) if s.strip())
    chunks: list[str] = []
    buf = ""
    for sentence in sentences:
        if len(sentence) > size:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(sentence)
            continue
        if buf and len(buf) + len(sentence) > size:
            chunks.append(buf)
            buf = sentence
        else:
            buf += sentence
    if buf:
        chunks.append(buf)
    return chunks


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
        semantic: bool = False,
    ) -> int:
        """摄取一段文档，返回生成的片段数；semantic=True 用语义感知分块"""
        if not text.strip():
            return 0
        if semantic:
            chunks = chunk_text_semantic(text, size=chunk_size, overlap=overlap)
        else:
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