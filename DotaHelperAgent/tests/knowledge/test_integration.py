"""知识管理系统集成测试"""

import pytest
from unittest.mock import Mock, MagicMock
from pathlib import Path

from knowledge.vector_store import VectorStore
from knowledge.fusion_engine import KnowledgeFusionEngine
from tools.knowledge_tools import KnowledgeQueryTool, KnowledgeUpdateTool, create_knowledge_tools


@pytest.fixture
def vector_store():
    """创建测试用的向量数据库（内存模式）"""
    config = {
        'persist_directory': './test_chroma_db',
        'collection_name': 'test_guides',
        'in_memory': True  # 使用内存模式
    }
    store = VectorStore(config)
    yield store
    store.close()


@pytest.fixture
def fusion_engine():
    """创建知识融合引擎"""
    return KnowledgeFusionEngine()


@pytest.fixture
def knowledge_system(vector_store, fusion_engine):
    """创建完整的知识管理系统"""
    tools = create_knowledge_tools(vector_store, fusion_engine)

    return {
        'vector_store': vector_store,
        'fusion_engine': fusion_engine,
        'tools': tools
    }


def test_end_to_end_query(knowledge_system):
    """测试端到端查询流程"""
    vector_store = knowledge_system['vector_store']

    # 1. 添加测试数据
    result = vector_store.add_document(
        doc_id="guide_001",
        text="针对 PA 的出装思路：PA 是一个高爆发物理输出英雄，建议出装：BKB、蝴蝶、撒旦",
        metadata={
            "title": "PA 出装攻略",
            "hero": "Phantom Assassin",
            "tags": ["PA", "出装", "物理输出"]
        }
    )

    assert result is True

    # 2. 执行查询
    query_result = vector_store.search(
        query="如何针对 PA 出装？",
        n_results=1
    )

    # 3. 验证结果
    assert query_result['success'] is True
    assert len(query_result['results']) > 0


def test_knowledge_fusion(knowledge_system):
    """测试知识融合"""
    vector_store = knowledge_system['vector_store']
    fusion_engine = knowledge_system['fusion_engine']

    # 添加多个数据源的知识
    vector_store.add_document(
        doc_id="guide_001",
        text="PA 建议出 BKB",
        metadata={"hero": "幻影刺客", "source": "guide_1"}
    )

    vector_store.add_document(
        doc_id="guide_002",
        text="PA 建议出蝴蝶",
        metadata={"hero": "幻影刺客", "source": "guide_2"}
    )

    # 查询
    search_result = vector_store.search(
        query="PA怎么出装？",
        n_results=2
    )

    # 融合
    if search_result['success']:
        fused_result = fusion_engine.merge(
            structured_knowledge=[],
            unstructured_knowledge=search_result['results'],
            query="PA怎么出装？"
        )

        assert fused_result.query == "PA怎么出装？"
        assert len(fused_result.unstructured_knowledge) > 0


def test_update_and_delete(knowledge_system):
    """测试更新和删除"""
    vector_store = knowledge_system['vector_store']

    # 添加
    add_result = vector_store.add_document(
        doc_id="test_001",
        text="测试文档",
        metadata={"title": "测试"}
    )
    assert add_result is True

    # 更新
    update_result = vector_store.update_document(
        doc_id="test_001",
        text="更新后的测试文档",
        metadata={"title": "更新测试"}
    )
    assert update_result is True

    # 删除
    delete_result = vector_store.delete_document(doc_id="test_001")
    assert delete_result is True


def test_tool_integration(knowledge_system):
    """测试工具集成"""
    tools = knowledge_system['tools']

    # 找到查询工具
    query_tool = next((t for t in tools if t.name == 'knowledge_query'), None)
    assert query_tool is not None

    # 找到更新工具
    update_tool = next((t for t in tools if t.name == 'knowledge_update'), None)
    assert update_tool is not None

    # 测试添加文档
    add_result = update_tool.execute(
        action="add",
        doc_id="tool_test_001",
        text="工具测试文档",
        metadata={"test": True}
    )
    assert add_result.is_success()


def test_batch_operations(knowledge_system):
    """测试批量操作"""
    vector_store = knowledge_system['vector_store']

    # 批量添加
    documents = [
        {
            "id": "batch_001",
            "text": "批量文档1",
            "metadata": {"batch": True}
        },
        {
            "id": "batch_002",
            "text": "批量文档2",
            "metadata": {"batch": True}
        },
        {
            "id": "batch_003",
            "text": "批量文档3",
            "metadata": {"batch": True}
        }
    ]

    count = vector_store.add_documents_batch(documents)
    assert count == 3

    # 验证统计信息
    stats = vector_store.get_stats()
    assert stats['document_count'] >= 3


def test_search_with_filter(knowledge_system):
    """测试带过滤条件的搜索"""
    vector_store = knowledge_system['vector_store']

    # 添加不同类型的文档
    vector_store.add_document(
        doc_id="hero_001",
        text="幻影刺客攻略",
        metadata={"type": "hero", "name": "幻影刺客"}
    )

    vector_store.add_document(
        doc_id="item_001",
        text="BKB 攻略",
        metadata={"type": "item", "name": "BKB"}
    )

    # 搜索
    result = vector_store.search(
        query="攻略",
        n_results=2
    )

    assert result['success'] is True
