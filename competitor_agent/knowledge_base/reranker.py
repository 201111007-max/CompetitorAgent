"""bge-reranker 精排层（设计文档 93 §2.2，决策 5/6/7）

hybrid 召回 top 15 候选后，用 sentence-transformers ``CrossEncoder``
（``BAAI/bge-reranker-v2-m3``，中英混合语料）对 (query, chunk) 对精排打分。

可用性语义与 vector_store 一致（设计文档 32 教训：代理 407 曾挂起 13 分钟）：
- ``is_available()`` 只探测本地 HF 缓存权重文件，**严禁触发网络**；
- 权重未缓存 / 加载失败 / 打分异常 → ``rerank`` 返回 None，调用方
  （Retriever）完全走现状路径（hybrid 结果直出），测试环境无权重时
  全部既有行为不变（回归安全阀）。

权重由用户自行下载（rag-warmup 之外，本层不提供下载入口）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from competitor_agent.knowledge_base.vector_store import _cached_weight_path

if TYPE_CHECKING:
    from competitor_agent.knowledge_base.competitor_store import TextChunk

logger = logging.getLogger("competitor_agent.knowledge_base.reranker")

DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"


class CrossEncoderReranker:
    """CrossEncoder 精排器：本地权重探测 + 自动降级。

    cross_encoder 参数可注入 stub（测试确定性）；注入即视为可用，
    不做本地权重探测。模型懒加载——不可用路径零开销。
    """

    def __init__(self, model_name: str = DEFAULT_RERANKER_MODEL, cross_encoder: Any = None) -> None:
        self._model_name = model_name
        self._model: Any = cross_encoder
        self._load_failed = False

    @property
    def model_name(self) -> str:
        """精排模型名（启动状态日志用，与 VectorStore.model_name 同风格）。"""
        return self._model_name

    def is_available(self) -> bool:
        """本地权重探测（不触网）：注入模型恒可用；否则须 HF 缓存已有权重文件。"""
        if self._model is not None:
            return True
        if self._load_failed:
            return False
        return _cached_weight_path(self._model_name) is not None

    def rerank(
        self, query: str, chunks: list[TextChunk], top_k: int = 5
    ) -> list[tuple[TextChunk, float]] | None:
        """对候选精排，返回 [(chunk, score)] 按分数降序（至多 top_k 条）。

        不可用 / 模型加载失败 / 打分异常 → None（调用方降级 hybrid 排序）。
        """
        if not chunks or not self.is_available():
            return None
        model = self._ensure_model()
        if model is None:
            return None
        try:
            pairs = [(query, c.text) for c in chunks]
            scores = model.predict(pairs)
        except Exception:
            logger.warning("reranker 打分失败，降级 hybrid 排序", exc_info=True)
            return None
        scored = [(c, float(s)) for c, s in zip(chunks, scores)]
        scored.sort(key=lambda kv: kv[1], reverse=True)
        return scored[:top_k]

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self._model_name)
        except Exception as exc:  # noqa: BLE001 - 权重损坏/依赖缺失：标记不可用，降级
            self._load_failed = True
            logger.warning("加载 reranker 模型失败: %s", exc)
            return None
        return self._model
