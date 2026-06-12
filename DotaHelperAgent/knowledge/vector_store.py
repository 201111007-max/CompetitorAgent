"""向量数据库客户端 - 基于 Chroma"""

from typing import List, Dict, Any, Optional
from pathlib import Path
import os

from utils.log_config import get_logger

logger = get_logger("vector_store", component="knowledge")


class VectorStore:
    """向量数据库客户端

    功能：
    - 攻略文档向量化存储
    - 语义检索
    - 元数据过滤
    """

    def __init__(self, config: Dict[str, Any]):
        """初始化向量数据库

        Args:
            config: 配置字典，包含：
                - persist_directory: 持久化目录
                - collection_name: 集合名称
                - embedding_model: Embedding 模型
                - embedding_dimension: 向量维度
        """
        self.config = config
        self.persist_dir = Path(config.get('persist_directory', './data/chroma_db'))
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        # 延迟导入 chromadb
        self._chromadb = None
        self._client = None
        self._collection = None
        self._embedding_func = None

        # 配置
        self.collection_name = config.get('collection_name', 'dota_guides')
        self.embedding_model = config.get('embedding_model', 'text-embedding-3-small')
        self.embedding_dimension = config.get('embedding_dimension', 1536)

        logger.info(f"向量数据库配置完成: {self.collection_name}")

    def _ensure_initialized(self):
        """确保数据库已初始化"""
        if self._client is None:
            self._initialize_client()

    def _initialize_client(self):
        """初始化 Chroma 客户端"""
        try:
            import chromadb

            self._chromadb = chromadb

            # 使用新的 Chroma API
            if self.config.get('in_memory', False):
                # 内存模式
                self._client = chromadb.EphemeralClient()
            else:
                # 持久化模式
                self._client = chromadb.PersistentClient(path=str(self.persist_dir))

            # 创建或获取集合
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"description": "Dota 2 攻略文档"}
            )

            logger.info(f"向量数据库初始化完成: {self.collection_name}")

        except Exception as e:
            logger.error(f"向量数据库初始化失败: {e}")
            raise

    def _get_embedding(self, text: str) -> List[float]:
        """获取文本的向量表示

        Args:
            text: 输入文本

        Returns:
            向量表示
        """
        try:
            import openai

            # 使用 OpenAI Embedding API
            response = openai.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            return response.data[0].embedding

        except Exception as e:
            logger.warning(f"OpenAI Embedding 失败，使用本地模型: {e}")
            return self._get_local_embedding(text)

    def _get_local_embedding(self, text: str) -> List[float]:
        """使用本地模型获取向量

        Args:
            text: 输入文本

        Returns:
            向量表示
        """
        try:
            from sentence_transformers import SentenceTransformer

            # 使用缓存避免重复加载模型
            if not hasattr(self, '_local_model'):
                self._local_model = SentenceTransformer('all-MiniLM-L6-v2')

            embedding = self._local_model.encode(text)
            return embedding.tolist()

        except Exception as e:
            logger.error(f"本地 Embedding 失败: {e}")
            # 返回零向量作为后备
            return [0.0] * 384

    def add_document(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """添加文档到向量数据库

        Args:
            doc_id: 文档ID
            text: 文档文本
            metadata: 元数据（标题、作者、标签等）

        Returns:
            是否成功
        """
        self._ensure_initialized()

        try:
            # 获取向量
            embedding = self._get_embedding(text)

            # 添加到集合
            self._collection.add(
                ids=[doc_id],
                documents=[text],
                metadatas=[metadata or {}],
                embeddings=[embedding]
            )

            logger.info(f"添加文档成功: {doc_id}")
            return True

        except Exception as e:
            logger.error(f"添加文档失败: {doc_id}, 错误: {e}")
            return False

    def add_documents_batch(
        self,
        documents: List[Dict[str, Any]]
    ) -> int:
        """批量添加文档

        Args:
            documents: 文档列表，每个文档包含 id, text, metadata

        Returns:
            成功添加的数量
        """
        self._ensure_initialized()

        if not documents:
            return 0

        ids = [doc['id'] for doc in documents]
        texts = [doc['text'] for doc in documents]
        metadatas = [doc.get('metadata', {}) for doc in documents]

        try:
            # 批量获取向量
            embeddings = [self._get_embedding(text) for text in texts]

            self._collection.add(
                ids=ids,
                documents=texts,
                metadatas=metadatas,
                embeddings=embeddings
            )

            logger.info(f"批量添加文档成功: {len(ids)} 个")
            return len(ids)

        except Exception as e:
            logger.error(f"批量添加文档失败: {e}")
            return 0

    def search(
        self,
        query: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
        where_document: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """语义检索

        Args:
            query: 查询文本
            n_results: 返回结果数量
            where: 元数据过滤条件
            where_document: 文档内容过滤条件

        Returns:
            检索结果
        """
        self._ensure_initialized()

        try:
            # 获取查询向量
            query_embedding = self._get_embedding(query)

            # 执行检索
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where,
                where_document=where_document
            )

            # 格式化结果
            formatted_results = []
            if results['ids'] and len(results['ids'][0]) > 0:
                for i in range(len(results['ids'][0])):
                    formatted_results.append({
                        'id': results['ids'][0][i],
                        'text': results['documents'][0][i] if results.get('documents') else '',
                        'metadata': results['metadatas'][0][i] if results.get('metadatas') else {},
                        'distance': results['distances'][0][i] if results.get('distances') else None
                    })

            logger.info(f"检索完成: 查询='{query}', 结果数={len(formatted_results)}")
            return {
                'success': True,
                'results': formatted_results,
                'query': query
            }

        except Exception as e:
            logger.error(f"检索失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'results': [],
                'query': query
            }

    def delete_document(self, doc_id: str) -> bool:
        """删除文档

        Args:
            doc_id: 文档ID

        Returns:
            是否成功
        """
        self._ensure_initialized()

        try:
            self._collection.delete(ids=[doc_id])
            logger.info(f"删除文档成功: {doc_id}")
            return True

        except Exception as e:
            logger.error(f"删除文档失败: {doc_id}, 错误: {e}")
            return False

    def update_document(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """更新文档

        Args:
            doc_id: 文档ID
            text: 新的文档文本
            metadata: 新的元数据

        Returns:
            是否成功
        """
        self._ensure_initialized()

        try:
            # Chroma 不支持直接更新，需要先删除再添加
            self._collection.delete(ids=[doc_id])

            # 获取向量
            embedding = self._get_embedding(text)

            # 添加新文档
            self._collection.add(
                ids=[doc_id],
                documents=[text],
                metadatas=[metadata or {}],
                embeddings=[embedding]
            )

            logger.info(f"更新文档成功: {doc_id}")
            return True

        except Exception as e:
            logger.error(f"更新文档失败: {doc_id}, 错误: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息

        Returns:
            统计信息字典
        """
        self._ensure_initialized()

        try:
            count = self._collection.count()
            return {
                'collection_name': self.collection_name,
                'document_count': count,
                'persist_directory': str(self.persist_dir),
                'embedding_model': self.embedding_model
            }

        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {
                'collection_name': self.collection_name,
                'document_count': 0,
                'persist_directory': str(self.persist_dir),
                'error': str(e)
            }

    def clear(self) -> bool:
        """清空集合

        Returns:
            是否成功
        """
        self._ensure_initialized()

        try:
            # 获取所有文档ID
            results = self._collection.get()
            if results['ids']:
                self._collection.delete(ids=results['ids'])

            logger.info(f"清空集合成功: {self.collection_name}")
            return True

        except Exception as e:
            logger.error(f"清空集合失败: {e}")
            return False

    def close(self) -> None:
        """关闭数据库连接，释放资源"""
        try:
            if self._client is not None:
                # Chroma 的 PersistentClient 需要手动释放资源
                # 在新版本中，删除 client 引用即可
                self._collection = None
                self._client = None
                logger.info(f"向量数据库连接已关闭: {self.collection_name}")
        except Exception as e:
            logger.error(f"关闭数据库连接失败: {e}")
