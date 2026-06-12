"""知识管理工具 - 提供知识查询和更新接口"""

from typing import Dict, Any, Optional, List
from tools.base import Tool, ToolResult, ToolStatus
from knowledge.vector_store import VectorStore
from knowledge.fusion_engine import KnowledgeFusionEngine
from utils.log_config import get_logger

logger = get_logger("knowledge_tools", component="tools")


class KnowledgeQueryTool(Tool):
    """知识查询工具

    功能：
    - 查询非结构化知识（向量检索）
    - 查询结构化知识（知识图谱）
    - 查询融合知识（多源融合）
    """

    def __init__(self, vector_store: VectorStore, fusion_engine: KnowledgeFusionEngine):
        """初始化知识查询工具

        Args:
            vector_store: 向量数据库客户端
            fusion_engine: 知识融合引擎
        """
        self.vector_store = vector_store
        self.fusion_engine = fusion_engine

        super().__init__(
            name="knowledge_query",
            description="查询知识库，支持非结构化知识检索、结构化知识查询和融合知识查询",
            parameters={
                "query": str,
                "knowledge_type": str,
                "n_results": int
            },
            func=self._execute_query,
            examples=[
                "knowledge_query(query='PA怎么出装？', knowledge_type='fused')",
                "knowledge_query(query='幻影刺客攻略', knowledge_type='unstructured', n_results=5)"
            ],
            category="knowledge"
        )

    def _execute_query(
        self,
        query: str,
        knowledge_type: str = "fused",
        n_results: int = 5
    ) -> Dict[str, Any]:
        """执行知识查询

        Args:
            query: 查询文本
            knowledge_type: 知识类型（"unstructured" | "structured" | "fused"）
            n_results: 返回结果数量

        Returns:
            查询结果
        """
        logger.info(f"知识查询: query='{query}', type={knowledge_type}")

        result = {}

        if knowledge_type in ["unstructured", "fused"]:
            # 非结构化知识检索
            unstructured_result = self.vector_store.search(
                query=query,
                n_results=n_results
            )
            result['unstructured'] = unstructured_result

        if knowledge_type in ["structured", "fused"]:
            # 结构化知识查询（目前使用模拟数据）
            # TODO: 集成知识图谱后实现
            result['structured'] = {
                'success': True,
                'results': [],
                'query': query
            }

        if knowledge_type == "fused":
            # 融合知识
            structured_knowledge = result.get('structured', {}).get('results', [])
            unstructured_knowledge = result.get('unstructured', {}).get('results', [])

            fused_result = self.fusion_engine.merge(
                structured_knowledge=structured_knowledge,
                unstructured_knowledge=unstructured_knowledge,
                query=query
            )
            result['fused'] = fused_result.to_dict()

        return result


class KnowledgeUpdateTool(Tool):
    """知识更新工具

    功能：
    - 添加知识
    - 更新知识
    - 删除知识
    """

    def __init__(self, vector_store: VectorStore):
        """初始化知识更新工具

        Args:
            vector_store: 向量数据库客户端
        """
        self.vector_store = vector_store

        super().__init__(
            name="knowledge_update",
            description="更新知识库，支持添加、更新和删除知识",
            parameters={
                "action": str,
                "doc_id": str,
                "text": str,
                "metadata": dict
            },
            func=self._execute_update,
            examples=[
                "knowledge_update(action='add', doc_id='guide_001', text='PA攻略', metadata={'hero': '幻影刺客'})",
                "knowledge_update(action='delete', doc_id='guide_001')"
            ],
            category="knowledge"
        )

    def _execute_update(
        self,
        action: str,
        doc_id: str,
        text: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """执行知识更新

        Args:
            action: 操作类型（"add" | "update" | "delete"）
            doc_id: 文档ID
            text: 文档文本（添加和更新时需要）
            metadata: 元数据（添加和更新时可选）

        Returns:
            操作结果
        """
        logger.info(f"知识更新: action={action}, doc_id={doc_id}")

        if action == "add":
            if text is None:
                raise ValueError("添加操作需要提供 text 参数")

            success = self.vector_store.add_document(
                doc_id=doc_id,
                text=text,
                metadata=metadata or {}
            )
            return {
                'success': success,
                'action': action,
                'doc_id': doc_id
            }

        elif action == "update":
            if text is None:
                raise ValueError("更新操作需要提供 text 参数")

            success = self.vector_store.update_document(
                doc_id=doc_id,
                text=text,
                metadata=metadata
            )
            return {
                'success': success,
                'action': action,
                'doc_id': doc_id
            }

        elif action == "delete":
            success = self.vector_store.delete_document(doc_id=doc_id)
            return {
                'success': success,
                'action': action,
                'doc_id': doc_id
            }

        else:
            raise ValueError(f"不支持的操作: {action}")


class KnowledgeStatsTool(Tool):
    """知识统计工具

    功能：
    - 获取知识库统计信息
    """

    def __init__(self, vector_store: VectorStore):
        """初始化知识统计工具

        Args:
            vector_store: 向量数据库客户端
        """
        self.vector_store = vector_store

        super().__init__(
            name="knowledge_stats",
            description="获取知识库统计信息",
            parameters={},
            func=self._execute_stats,
            examples=[
                "knowledge_stats()"
            ],
            category="knowledge"
        )

    def _execute_stats(self) -> Dict[str, Any]:
        """执行知识统计

        Returns:
            统计信息
        """
        logger.info("获取知识库统计信息")

        stats = self.vector_store.get_stats()
        return stats


def create_knowledge_tools(
    vector_store: VectorStore,
    fusion_engine: KnowledgeFusionEngine
) -> List[Tool]:
    """创建知识管理工具集合

    Args:
        vector_store: 向量数据库客户端
        fusion_engine: 知识融合引擎

    Returns:
        工具列表
    """
    return [
        KnowledgeQueryTool(vector_store, fusion_engine),
        KnowledgeUpdateTool(vector_store),
        KnowledgeStatsTool(vector_store)
    ]
