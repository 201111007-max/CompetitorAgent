"""知识工具测试"""

import pytest
from unittest.mock import Mock, MagicMock
from tools.knowledge_tools import KnowledgeQueryTool, KnowledgeUpdateTool
from knowledge.vector_store import VectorStore
from knowledge.fusion_engine import KnowledgeFusionEngine, FusedKnowledge


@pytest.fixture
def mock_vector_store():
    """创建模拟的向量数据库"""
    mock = Mock(spec=VectorStore)
    mock.search.return_value = {
        'success': True,
        'results': [
            {
                'id': 'guide_001',
                'text': 'PA 出装攻略',
                'metadata': {'hero': '幻影刺客'}
            }
        ]
    }
    mock.add_document.return_value = True
    mock.delete_document.return_value = True
    mock.update_document.return_value = True
    return mock


@pytest.fixture
def mock_fusion_engine():
    """创建模拟的知识融合引擎"""
    mock = Mock(spec=KnowledgeFusionEngine)

    # 创建模拟的融合结果
    fused_result = FusedKnowledge(
        query="PA怎么出装？",
        structured_knowledge=[{"hero": "幻影刺客", "item": "BKB", "source": "opendota"}],
        unstructured_knowledge=[{"hero": "幻影刺客", "item": "蝴蝶", "source": "guide"}],
        conflicts=[],
        confidence=0.8,
        sources=["opendota", "guide"],
        timestamp=1700000000.0
    )
    mock.merge.return_value = fused_result

    return mock


@pytest.fixture
def query_tool(mock_vector_store, mock_fusion_engine):
    """创建知识查询工具"""
    return KnowledgeQueryTool(mock_vector_store, mock_fusion_engine)


@pytest.fixture
def update_tool(mock_vector_store):
    """创建知识更新工具"""
    return KnowledgeUpdateTool(mock_vector_store)


def test_query_knowledge_unstructured(query_tool, mock_vector_store):
    """测试非结构化知识查询"""
    result = query_tool.execute(
        query="PA怎么出装？",
        knowledge_type="unstructured"
    )

    assert result.is_success()
    assert 'unstructured' in result.data
    mock_vector_store.search.assert_called_once()


def test_query_knowledge_structured(query_tool, mock_fusion_engine):
    """测试结构化知识查询"""
    result = query_tool.execute(
        query="PA怎么出装？",
        knowledge_type="structured"
    )

    assert result.is_success()
    assert 'structured' in result.data


def test_query_knowledge_fused(query_tool, mock_fusion_engine):
    """测试融合知识查询"""
    result = query_tool.execute(
        query="PA怎么出装？",
        knowledge_type="fused"
    )

    assert result.is_success()
    assert 'fused' in result.data


def test_update_knowledge_add(update_tool, mock_vector_store):
    """测试添加知识"""
    result = update_tool.execute(
        action="add",
        doc_id="test_001",
        text="测试文档",
        metadata={"title": "测试"}
    )

    assert result.is_success()
    mock_vector_store.add_document.assert_called_once()


def test_update_knowledge_delete(update_tool, mock_vector_store):
    """测试删除知识"""
    result = update_tool.execute(
        action="delete",
        doc_id="test_001"
    )

    assert result.is_success()
    mock_vector_store.delete_document.assert_called_once()


def test_update_knowledge_update(update_tool, mock_vector_store):
    """测试更新知识"""
    result = update_tool.execute(
        action="update",
        doc_id="test_001",
        text="更新后的文档",
        metadata={"title": "更新测试"}
    )

    assert result.is_success()
    mock_vector_store.update_document.assert_called_once()


def test_update_knowledge_invalid_action(update_tool):
    """测试无效操作"""
    result = update_tool.execute(
        action="invalid",
        doc_id="test_001"
    )

    assert not result.is_success()
    assert "不支持的操作" in result.error


def test_query_tool_schema(query_tool):
    """测试查询工具的 Schema"""
    schema = query_tool.get_schema()

    assert schema['name'] == 'knowledge_query'
    assert 'parameters' in schema
    assert 'query' in schema['parameters']['properties']


def test_update_tool_schema(update_tool):
    """测试更新工具的 Schema"""
    schema = update_tool.get_schema()

    assert schema['name'] == 'knowledge_update'
    assert 'parameters' in schema
    assert 'action' in schema['parameters']['properties']
