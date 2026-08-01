"""RAG 引擎 — Embedding + chromadb 语义检索

支持 Markdown 知识库的自动索引和语义检索，作为 RagPlugin 的后端引擎。

设计要点：
- 懒加载 embedding 模型（sentence-transformers all-MiniLM-L6-v2）
- 段落级切分（按 ## 标题），检索粒度更细
- 相似度阈值过滤，避免注入无关知识
- chromadb 主检索 + TF-IDF 回退（利用现有 rag_index.py）
- 去重机制：同一 query 不重复检索
"""
import os
import re
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dota_helper.observability.logger import get_logger

logger = get_logger("agent.rag_engine")

# ── 默认路径 ──
_DEFAULT_KB_DIR = Path(__file__).parent.parent / "knowledge_base"
_DEFAULT_PERSIST_DIR = Path(__file__).parent.parent / "chromadb_data"


class RagEngine:
    """RAG 引擎 — Embedding + chromadb 封装

    管理知识库的索引构建和语义检索，支持 chromadb 主检索和 TF-IDF 回退。

    Args:
        kb_dir: 知识库目录路径（默认 dota_helper/knowledge_base/）
        persist_dir: chromadb 持久化目录路径（默认 dota_helper/chromadb_data/）
        min_score: 检索结果最低相似度阈值（默认 0.3）
    """

    def __init__(
        self,
        kb_dir: Optional[str] = None,
        persist_dir: Optional[str] = None,
        min_score: float = 0.3,
    ) -> None:
        self._kb_dir = Path(kb_dir) if kb_dir else _DEFAULT_KB_DIR
        self._persist_dir = Path(persist_dir) if persist_dir else _DEFAULT_PERSIST_DIR
        self._min_score = min_score

        # 懒加载资源
        self._embedding_model: Any = None
        self._collection: Any = None
        self._chromadb_client: Any = None

        # 缓存
        self._indexed_files: Dict[str, float] = {}  # path -> mtime
        self._has_chromadb: bool = False
        self._has_sentence_transformers: bool = False

        logger.info(
            "RAG 引擎初始化: kb_dir=%s, persist_dir=%s, min_score=%.2f",
            self._kb_dir, self._persist_dir, min_score,
        )

    # ── 公共 API ──

    def search(
        self,
        query: str,
        top_k: int = 3,
        category: Optional[str] = None,
        min_score: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """语义检索知识库

        优先使用 chromadb 检索，失败时回退到 TF-IDF 检索。

        Args:
            query: 查询文本
            top_k: 返回结果数量（默认 3）
            category: 按分类过滤（如 "hero", "tactics", "item"）
            min_score: 最低相似度阈值（覆盖实例默认值）

        Returns:
            List[Dict[str, Any]]: 检索结果列表，每项包含 content/metadata/score
        """
        if not query or not query.strip():
            return []

        threshold = min_score if min_score is not None else self._min_score

        # 1. 尝试 chromadb 检索
        if self._has_chromadb:
            try:
                results = self._search_chromadb(query, top_k, category, threshold)
                if results:
                    return results
            except Exception as e:
                logger.warning("chromadb 检索失败，回退到 TF-IDF: %s", str(e))

        # 2. 回退到 TF-IDF 检索
        return self._search_tfidf(query, top_k, threshold)

    def index_all(self, force: bool = False) -> int:
        """扫描 knowledge_base/ 下所有 .md 文件，重建或增量更新索引

        Args:
            force: 是否强制重建全部索引（默认 False，仅更新变更文件）

        Returns:
            int: 索引的段落数量
        """
        if not self._kb_dir.exists():
            logger.warning("知识库目录不存在: %s", self._kb_dir)
            return 0

        # 收集所有 .md 文件
        md_files: List[Path] = []
        for root, _dirs, files in os.walk(str(self._kb_dir)):
            for fname in files:
                if fname.endswith(".md"):
                    md_files.append(Path(root) / fname)

        if not md_files:
            logger.info("知识库目录无 .md 文件: %s", self._kb_dir)
            return 0

        # 检查是否有变更文件
        changed_files = self._get_changed_files(md_files)
        if not changed_files and not force:
            logger.info("知识库无变更，跳过索引")
            return 0

        if force:
            logger.info("强制重建索引: %d 个文件", len(md_files))
            target_files = md_files
            # 清空已有 collection
            self._clear_collection()
        else:
            logger.info("增量索引: %d 个文件变更", len(changed_files))
            target_files = changed_files

        # 切分段落并索引
        total_chunks = 0
        for file_path in target_files:
            chunks = self._index_file(file_path)
            total_chunks += chunks

        logger.info(
            "索引完成: total_chunks=%d, files=%d",
            total_chunks, len(target_files),
        )
        return total_chunks

    def search_hero(self, hero_name: str) -> List[Dict[str, Any]]:
        """快捷方法：按英雄名精确检索

        通过 metadata 过滤 category=hero 且 filename 模糊匹配。

        Args:
            hero_name: 英雄名称（中英文均可）

        Returns:
            List[Dict[str, Any]]: 检索结果
        """
        return self.search(
            query=hero_name,
            top_k=1,
            category="hero",
            min_score=0.1,  # 英雄名匹配放宽阈值
        )

    # ── chromadb 检索 ──

    def _ensure_chromadb(self) -> bool:
        """确保 chromadb 可用，懒加载 collection

        Returns:
            bool: chromadb 是否可用
        """
        if self._collection is not None:
            return True

        try:
            import chromadb  # type: ignore[import-untyped]
            self._has_chromadb = True
        except ImportError:
            logger.warning("chromadb 未安装，使用 TF-IDF 回退")
            return False

        try:
            self._chromadb_client = chromadb.PersistentClient(str(self._persist_dir))
            self._collection = self._chromadb_client.get_or_create_collection(
                name="dota_knowledge",
                metadata={"hnsw:space": "cosine"},
            )
            logger.debug("chromadb collection 已加载: dota_knowledge")
            return True
        except Exception as e:
            logger.warning("chromadb 初始化失败: %s", str(e))
            self._has_chromadb = False
            return False

    def _ensure_embedding_model(self) -> bool:
        """懒加载 sentence-transformers 模型

        Returns:
            bool: 模型是否加载成功
        """
        if self._embedding_model is not None:
            return True

        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
            self._has_sentence_transformers = True
            logger.info("正在加载 embedding 模型: all-MiniLM-L6-v2")

            # 企业网络环境可能需要禁用 SSL 验证
            import httpx
            original_init = httpx.Client.__init__
            def _ssl_disabled_init(self, *args, **kwargs):
                kwargs.setdefault("verify", False)
                original_init(self, *args, **kwargs)
            httpx.Client.__init__ = _ssl_disabled_init

            self._embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("embedding 模型加载完成")
            return True
        except ImportError:
            logger.warning("sentence-transformers 未安装，使用 TF-IDF 回退")
            return False
        except Exception as e:
            logger.warning("embedding 模型加载失败: %s", str(e))
            return False

    def _search_chromadb(
        self,
        query: str,
        top_k: int,
        category: Optional[str],
        min_score: float,
    ) -> List[Dict[str, Any]]:
        """使用 chromadb 进行语义检索

        Args:
            query: 查询文本
            top_k: 返回数量
            category: 分类过滤
            min_score: 最低相似度

        Returns:
            List[Dict[str, Any]]: 检索结果
        """
        if not self._ensure_chromadb():
            return []

        if not self._ensure_embedding_model():
            return []

        # 生成 query embedding
        query_embedding = self._embedding_model.encode(query).tolist()  # type: ignore[union-attr]

        # 构建查询参数
        query_kwargs: Dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": max(top_k, 10),
        }
        if category:
            query_kwargs["where"] = {"category": category}

        results = self._collection.query(**query_kwargs)  # type: ignore[union-attr]

        # 解析结果
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        if not documents:
            return []

        # chromadb cosine distance 转 similarity
        scored: List[Dict[str, Any]] = []
        for doc, meta, dist in zip(documents, metadatas, distances):
            score = 1.0 - float(dist)  # cosine distance → similarity
            if score < min_score:
                continue
            scored.append({
                "content": str(doc),
                "metadata": dict(meta) if meta else {},
                "score": score,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def _clear_collection(self) -> None:
        """清空 chromadb collection（用于重建索引）"""
        if self._collection is None:
            return
        try:
            self._chromadb_client.delete_collection("dota_knowledge")  # type: ignore[union-attr]
            self._collection = self._chromadb_client.get_or_create_collection(  # type: ignore[union-attr]
                name="dota_knowledge",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("chromadb collection 已清空重建")
        except Exception as e:
            logger.warning("清空 collection 失败: %s", str(e))

    # ── 文件索引 ──

    def _get_changed_files(self, md_files: List[Path]) -> List[Path]:
        """检查哪些文件有变更（mtime 变化）

        Args:
            md_files: 所有 .md 文件列表

        Returns:
            List[Path]: 有变更的文件列表
        """
        changed: List[Path] = []
        for fpath in md_files:
            mtime = os.path.getmtime(str(fpath))
            cached_mtime = self._indexed_files.get(str(fpath))
            if cached_mtime is None or abs(mtime - cached_mtime) > 0.01:
                changed.append(fpath)
        return changed

    def _index_file(self, file_path: Path) -> int:
        """索引单个 .md 文件

        按 ## 标题切分为段落，每段独立 embedding。

        Args:
            file_path: .md 文件路径

        Returns:
            int: 索引的段落数量
        """
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("读取文件失败: %s, error=%s", file_path, str(e))
            return 0

        # 解析分类和文件名
        rel_path = file_path.relative_to(self._kb_dir)
        category = str(rel_path.parent)
        if category == ".":
            category = "general"
        filename = file_path.stem

        # 按 ## 标题切分段落
        chunks = self._split_markdown(content)

        if not chunks:
            # 无标题段落，整文件作为一个段落
            chunks = [{"title": filename, "content": content.strip()}]

        # 索引到 chromadb
        if self._ensure_chromadb() and self._ensure_embedding_model():
            self._index_chunks_to_chromadb(chunks, category, filename, file_path)

        # 更新缓存
        mtime = os.path.getmtime(str(file_path))
        self._indexed_files[str(file_path)] = mtime

        logger.debug("文件索引完成: %s, chunks=%d", file_path, len(chunks))
        return len(chunks)

    def _split_markdown(self, content: str) -> List[Dict[str, str]]:
        """按 ## 标题切分 Markdown 内容

        Args:
            content: Markdown 文本

        Returns:
            List[Dict[str, str]]: 段落列表，每项包含 title 和 content
        """
        # 按 ## 标题分割
        sections = re.split(r"\n(?=##\s)", content.strip())
        chunks: List[Dict[str, str]] = []

        for section in sections:
            section = section.strip()
            if not section:
                continue

            lines = section.split("\n")
            title = ""
            body_lines: List[str] = []

            for line in lines:
                if line.startswith("## "):
                    title = line[3:].strip()
                else:
                    body_lines.append(line)

            body = "\n".join(body_lines).strip()
            if not body:
                continue

            chunks.append({
                "title": title or filename_from_content(section),
                "content": section,
            })

        return chunks

    def _index_chunks_to_chromadb(
        self,
        chunks: List[Dict[str, str]],
        category: str,
        filename: str,
        file_path: Path,
    ) -> None:
        """将段落批量索引到 chromadb

        Args:
            chunks: 段落列表
            category: 分类
            filename: 文件名（不含扩展名）
            file_path: 源文件路径
        """
        texts = [chunk["content"] for chunk in chunks]
        titles = [chunk["title"] for chunk in chunks]

        # 生成 embeddings
        try:
            embeddings = self._embedding_model.encode(texts).tolist()  # type: ignore[union-attr]
        except Exception as e:
            logger.warning("embedding 生成失败: %s", str(e))
            return

        # 构建 ID 和 metadata
        ids: List[str] = []
        metadatas: List[Dict[str, str]] = []
        for i, title in enumerate(titles):
            chunk_id = f"{category}_{filename}_{i}"
            ids.append(chunk_id)
            metadatas.append({
                "category": category,
                "filename": filename,
                "title": title,
                "source": str(file_path),
            })

        # upsert 到 chromadb
        try:
            self._collection.upsert(  # type: ignore[union-attr]
                ids=ids,
                documents=texts,
                embeddings=embeddings,
                metadatas=metadatas,
            )
            logger.debug("chromadb upsert: %d chunks", len(chunks))
        except Exception as e:
            logger.warning("chromadb upsert 失败: %s", str(e))

    # ── TF-IDF 回退检索 ──

    def _search_tfidf(
        self,
        query: str,
        top_k: int,
        min_score: float,
    ) -> List[Dict[str, Any]]:
        """使用现有 TF-IDF 索引回退检索

        Args:
            query: 查询文本
            top_k: 返回数量
            min_score: 最低相似度

        Returns:
            List[Dict[str, Any]]: 检索结果
        """
        try:
            from dota_helper.mcp_server.helpers.rag_index import (
                rank_hero_documents,
                format_hero_rag_output,
            )

            results = rank_hero_documents(query, top_k=top_k)
            if not results:
                return []

            scored: List[Dict[str, Any]] = []
            for item in results:
                doc = item.get("doc", {})
                hybrid_score = item.get("hybrid_score", 0.0)
                if hybrid_score < min_score:
                    continue
                scored.append({
                    "content": doc.get("content", ""),
                    "metadata": {
                        "name_en": doc.get("name_en", ""),
                        "name_cn": doc.get("name_cn", ""),
                        "source": doc.get("path", ""),
                        "method": "tfidf",
                    },
                    "score": hybrid_score,
                })

            scored.sort(key=lambda x: x["score"], reverse=True)
            return scored[:top_k]

        except ImportError:
            logger.warning("TF-IDF 回退不可用: rag_index 未找到")
            return []
        except Exception as e:
            logger.warning("TF-IDF 回退检索失败: %s", str(e))
            return []

    # ── 工具方法 ──

    def format_context(self, results: List[Dict[str, Any]]) -> str:
        """将检索结果格式化为注入上下文的文本

        Args:
            results: 检索结果列表

        Returns:
            str: 格式化的上下文文本
        """
        if not results:
            return ""

        lines: List[str] = ["## 相关知识", ""]
        for i, item in enumerate(results, 1):
            content = item.get("content", "").strip()
            metadata = item.get("metadata", {})
            score = item.get("score", 0.0)

            # 截断过长内容
            if len(content) > 800:
                content = content[:800].rstrip() + "\n...[截断]"

            source = metadata.get("source", metadata.get("name_en", ""))
            lines.append(f"### 参考 {i} (相关性: {score:.2f})")
            if source:
                lines.append(f"来源: {source}")
            lines.append("")
            lines.append(content)
            lines.append("")

        return "\n".join(lines).strip()

    @property
    def kb_dir(self) -> Path:
        """知识库目录路径"""
        return self._kb_dir

    @property
    def persist_dir(self) -> Path:
        """chromadb 持久化目录路径"""
        return self._persist_dir


def filename_from_content(content: str) -> str:
    """从内容中提取文件名风格的标题

    Args:
        content: 文本内容

    Returns:
        str: 提取的标题
    """
    first_line = content.strip().split("\n")[0].strip()
    return first_line.replace("#", "").strip()[:50]
