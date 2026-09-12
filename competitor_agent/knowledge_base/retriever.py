"""知识库检索（Retriever）— 混合检索 + 可选精排

检索策略：
1. 词袋余弦检索（默认，无需额外依赖）
2. 维度过滤：同一竞品优先返回命中维度的片段
3. 可选：若安装了 sentence-transformers/chromadb，则叠加向量检索（渐进增强）
4. 可选（设计文档 93 §2.2）：bge-reranker 对 hybrid top 15 候选精排后取 top_k；
   reranker 不可用/未注入时完全走现状路径（回归安全阀）
"""

from __future__ import annotations

from competitor_agent.knowledge_base.competitor_store import CompetitorStore, TextChunk, tokenize
from competitor_agent.knowledge_base.reranker import CrossEncoderReranker

# 精排召回幅度（设计文档 93 决策 7）：hybrid top 15 候选精排取 top 5
_RERANK_RECALL = 15


class Retriever:
    """混合检索器"""

    def __init__(self, store: CompetitorStore, reranker: CrossEncoderReranker | None = None) -> None:
        self._store = store
        self._reranker = reranker

    def retrieve(
        self,
        query: str,
        competitor: str,
        dimension: str = "",
        top_k: int = 5,
        strategy: str = "hybrid",
    ) -> list[TextChunk]:
        """检索与查询最相关的文档片段（同竞品优先）。

        strategy="hybrid"（默认）：词袋+向量混合融合；向量层不可用时自动降级词袋。
        strategy="lexical"：纯词袋（消融对比用，不经精排）。
        reranker 可用时：hybrid 召回 top 15 → CrossEncoder 精排 → 竞品优先+维度加权；
        不可用/精排失败时与现状逐位一致。
        """
        reranker = self._reranker if strategy != "lexical" else None
        use_rerank = reranker is not None and reranker.is_available()
        if strategy == "lexical":
            scored = self._store.search(query, top_k=top_k * 3)
        else:
            recall = max(top_k * 3, _RERANK_RECALL) if use_rerank else top_k * 3
            scored = [(c, s) for c, s, _src in self._store.search_hybrid(query, top_k=recall)]
        if use_rerank and scored and reranker is not None:
            reranked = reranker.rerank(query, [c for c, _ in scored], top_k=len(scored))
            if reranked is not None:
                scored = reranked
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
        """按竞品×维度直接取片段（无需查询词）；时效衰减排序（新片段优先，同龄保持摄入序）"""
        chunks = self._store.by_competitor(competitor)
        by_dim = [c for c in chunks if c.dimension == dimension]
        now = self._store.current_time()
        by_dim.sort(key=lambda c: self._store.decay_factor(c, now), reverse=True)
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
