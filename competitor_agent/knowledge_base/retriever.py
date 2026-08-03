"""知识库检索（Retriever）— 混合检索

检索策略：
1. 词袋余弦检索（默认，无需额外依赖）
2. 维度过滤：同一竞品优先返回命中维度的片段
3. 可选：若安装了 sentence-transformers/chromadb，则叠加向量检索（渐进增强）
"""
from __future__ import annotations

from competitor_agent.knowledge_base.competitor_store import CompetitorStore, TextChunk, tokenize


class Retriever:
    """混合检索器"""

    def __init__(self, store: CompetitorStore) -> None:
        self._store = store

    def retrieve(
        self,
        query: str,
        competitor: str,
        dimension: str = "",
        top_k: int = 5,
    ) -> list[TextChunk]:
        """检索与查询最相关的文档片段（同竞品优先）"""
        scored = self._store.search(query, top_k=top_k * 3)
        # 竞品过滤：优先同竞品，不足时放宽到全局
        same = [(c, s) for c, s in scored if c.competitor == competitor]
        others = [(c, s) for c, s in scored if c.competitor != competitor]
        ranked = _rank_by_dimension(same, dimension) + _rank_by_dimension(others, dimension)
        return [c for c, _ in ranked[:top_k]]

    def retrieve_by_dimension(
        self,
        competitor: str,
        dimension: str,
        top_k: int = 10,
    ) -> list[TextChunk]:
        """按竞品×维度直接取片段（无需查询词）"""
        chunks = self._store.by_competitor(competitor)
        by_dim = [c for c in chunks if c.dimension == dimension]
        return by_dim[:top_k]

    def exists(self, competitor: str) -> bool:
        return bool(self._store.by_competitor(competitor))


def _rank_by_dimension(items: list[tuple[TextChunk, float]], dimension: str) -> list[tuple[TextChunk, float]]:
    """维度匹配片段前置，保持原得分相对顺序"""
    if not dimension:
        return items
    dim_tokens = set(tokenize(dimension))
    matched = [(c, s + 1.0) for c, s in items if dim_tokens & set(tokenize(c.dimension))]
    rest = [(c, s) for c, s in items if not (dim_tokens & set(tokenize(c.dimension)))]
    matched.sort(key=lambda kv: kv[1], reverse=True)
    return matched + rest