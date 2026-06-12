"""向量数据库测试"""

import pytest
from knowledge.vector_store import VectorStore


@pytest.fixture
def vector_store():
    """创建测试用的向量数据库（使用内存模式）"""
    config = {
        'persist_directory': './test_chroma_db',
        'collection_name': 'test_collection',
        'embedding_model': 'text-embedding-3-small',
        'embedding_dimension': 1536,
        'in_memory': True  # 使用内存模式，避免文件锁定问题
    }
    store = VectorStore(config)
    yield store
    # 清理资源
    store.close()


def test_add_document(vector_store):
    """测试添加文档"""
    success = vector_store.add_document(
        doc_id="test_001",
        text="这是一个测试文档",
        metadata={"title": "测试文档", "author": "测试"}
    )
    assert success is True


def test_add_documents_batch(vector_store):
    """测试批量添加文档"""
    documents = [
        {
            "id": "test_001",
            "text": "文档1",
            "metadata": {"title": "文档1"}
        },
        {
            "id": "test_002",
            "text": "文档2",
            "metadata": {"title": "文档2"}
        }
    ]

    count = vector_store.add_documents_batch(documents)
    assert count == 2


def test_search(vector_store):
    """测试检索"""
    # 添加测试文档
    vector_store.add_document(
        doc_id="test_001",
        text="PA 是一个高爆发物理输出英雄",
        metadata={"hero": "Phantom Assassin"}
    )

    # 检索
    results = vector_store.search("如何针对 PA？", n_results=1)
    assert results['success'] is True
    assert len(results['results']) > 0


def test_delete_document(vector_store):
    """测试删除文档"""
    # 添加文档
    vector_store.add_document(
        doc_id="test_002",
        text="测试删除",
        metadata={}
    )

    # 删除
    success = vector_store.delete_document("test_002")
    assert success is True


def test_get_stats(vector_store):
    """测试获取统计信息"""
    stats = vector_store.get_stats()
    assert 'collection_name' in stats
    assert 'document_count' in stats


def test_update_document(vector_store):
    """测试更新文档"""
    # 添加文档
    vector_store.add_document(
        doc_id="test_003",
        text="原始文档",
        metadata={"version": 1}
    )

    # 更新文档
    success = vector_store.update_document(
        doc_id="test_003",
        text="更新后的文档",
        metadata={"version": 2}
    )
    assert success is True


def test_search_with_metadata_filter(vector_store):
    """测试带元数据过滤的检索"""
    # 添加多个文档
    vector_store.add_document(
        doc_id="test_004",
        text="PA 攻略",
        metadata={"hero": "幻影刺客", "type": "guide"}
    )
    vector_store.add_document(
        doc_id="test_005",
        text="Juggernaut 攻略",
        metadata={"hero": "主宰", "type": "guide"}
    )

    # 检索
    results = vector_store.search(
        "攻略",
        n_results=2,
        where={"hero": "幻影刺客"}
    )
    assert results['success'] is True
