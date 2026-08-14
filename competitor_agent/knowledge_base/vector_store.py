"""知识库向量层（VectorStore）— chromadb 集合 + 可插拔嵌入（设计文档 32）

嵌入函数可插拔，按以下优先级解析：
1. 注入的 callable（测试/评测用确定性 mock，CI 可复现）；
2. 字符串 ``"hash"``：内置确定性哈希嵌入（离线可用，无模型依赖）；
3. ``None``：若本地已缓存 ``model_name`` 的 sentence-transformers 模型则用它（语义嵌入，
   自动升级），否则视为不可用。

不可用时 ``is_available()`` 返回 False，调用方（CompetitorStore.search_hybrid / Retriever）
无缝降级纯词袋，保证无模型/无网络环境行为与现状一致。
"""

from __future__ import annotations

import hashlib
import logging
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("competitor_agent.knowledge_base.vector_store")

# 与 competitor_store 保持一致的中英文分词正则
_WORD_RE = re.compile(r"[a-z0-9一-鿿]+")


class VectorStoreUnavailableError(RuntimeError):
    """嵌入函数不可用（无模型缓存且未注入 embed_fn）。"""


def hash_embed(texts: list[str], dim: int = 256) -> list[list[float]]:
    """确定性哈希嵌入（特征哈希）：词元 + 中文字符 bigram 经双哈希投影到 dim 维，L2 归一化。

    离线可用、无模型、可复现；语义模型可用时由 sentence-transformers 路径替代。
    """
    import numpy as np

    out: list[list[float]] = []
    for text in texts:
        vec = np.zeros(dim, dtype=np.float64)
        tokens = _WORD_RE.findall(text.lower())
        features: set[str] = set()
        for t in tokens:
            features.add(t)
            if "一" <= t[0] <= "鿿" and len(t) >= 2:
                for i in range(len(t) - 1):
                    features.add(f"bi:{t[i : i + 2]}")
        for feature in features:
            h1 = int(hashlib.sha256(feature.encode()).hexdigest()[:8], 16)
            idx = h1 % dim
            sign = 1.0 if (h1 >> 31) & 1 else -1.0
            vec[idx] += sign
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        out.append(vec.tolist())
    return out


def _semantic_embedder_cached(model_name: str) -> bool:
    """模型权重是否已缓存（探测本地缓存，不触发网络下载）。

    仅探测权重文件（safetensors/bin）——config/tokenizer 已缓存而权重缺失
    （如下载中断）时仍视为不可用，避免 SentenceTransformer 构造时触发网络重试。
    """
    try:
        from huggingface_hub import try_to_load_from_cache

        for filename in ("model.safetensors", "pytorch_model.bin", "model.bin"):
            path = try_to_load_from_cache(model_name, filename)
            if isinstance(path, (str, Path)) and Path(path).exists():
                return True
        return False
    except Exception:
        return False


class VectorStore:
    """chromadb 向量集合：嵌入生成 + upsert + 语义检索。

    依赖（chromadb / 嵌入模型）不可用时 is_available() 返回 False，调用方降级词袋。
    chromadb 客户端与集合均懒创建——不可用路径零开销。
    """

    def __init__(
        self,
        collection_name: str = "competitor_chunks",
        model_name: str = "BAAI/bge-small-zh-v1.5",
        embed_fn: Callable[[list[str]], list[list[float]]] | str | None = None,
        data_dir: Path | str | None = None,
    ) -> None:
        self._collection_name = collection_name
        self._model_name = model_name
        self._embed_fn_arg = embed_fn
        # data_dir 为 None → 临时目录（不落盘，随进程回收）；给定则持久化到 data_dir/chroma
        self._data_dir = Path(data_dir) / "chroma" if data_dir else Path(
            tempfile.mkdtemp(prefix="chroma_")
        )
        self._client: Any = None
        self._collection: Any = None
        self._embed_fn: Callable[[list[str]], list[list[float]]] | None = None
        self._resolved = False

    # ---- 可用性 ----
    def is_available(self) -> bool:
        if not self._resolved:
            self._resolved = True
            self._embed_fn = self._resolve_embed_fn()
        return self._embed_fn is not None

    def _resolve_embed_fn(
        self,
    ) -> Callable[[list[str]], list[list[float]]] | None:
        arg = self._embed_fn_arg
        if callable(arg):
            return arg
        if arg == "hash":
            return hash_embed
        if arg is not None:
            return None
        if not _semantic_embedder_cached(self._model_name):
            logger.debug("向量模型 %s 未缓存，向量层降级词袋", self._model_name)
            return None
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(self._model_name)
            return model.encode  # type: ignore[return-value]
        except Exception as exc:  # pragma: no cover - 模型损坏等偶发
            logger.warning("加载向量模型失败: %s", exc)
            return None

    # ---- 嵌入 ----
    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.is_available():
            raise VectorStoreUnavailableError(
                f"向量嵌入不可用（模型 {self._model_name} 未缓存，且未注入 embed_fn）"
            )
        return list(self._embed_fn(texts))  # type: ignore[misc]

    # ---- chromadb 后端 ----
    def _ensure_client(self) -> None:
        if self._collection is not None:
            return
        import chromadb
        from chromadb.config import Settings

        self._client = chromadb.PersistentClient(
            path=str(self._data_dir), settings=Settings(anonymized_telemetry=False)
        )
        self._collection = self._client.get_or_create_collection(self._collection_name)

    def upsert(
        self,
        chunk_ids: list[str],
        vectors: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        self._ensure_client()
        self._collection.upsert(ids=chunk_ids, embeddings=vectors, metadatas=metadatas)

    def get_existing(self, chunk_ids: list[str]) -> set[str]:
        """返回已在集合中的 chunk_id 子集（增量同步用，避免重复嵌入与重复 id 冲突）。"""
        if not chunk_ids or self._collection is None:
            return set()
        res = self._collection.get(ids=chunk_ids, include=[])
        return set(res.get("ids") or [])

    def search(self, query_vec: list[float], top_k: int) -> list[tuple[str, float]]:
        """返回 [(chunk_id, distance)]，distance 越小越相似（L2，对归一化向量等价余弦）。"""
        self._ensure_client()
        if self.count() == 0:
            return []
        res = self._collection.query(
            query_embeddings=[query_vec], n_results=min(top_k, self.count())
        )
        ids = (res.get("ids") or [[]])[0]
        distances = (res.get("distances") or [[]])[0]
        return list(zip(ids, distances))

    def clear(self) -> None:
        if self._collection is None:
            return
        self._client.delete_collection(self._collection_name)
        self._collection = self._client.get_or_create_collection(self._collection_name)

    def count(self) -> int:
        if self._collection is None:
            return 0
        return int(self._collection.count())
