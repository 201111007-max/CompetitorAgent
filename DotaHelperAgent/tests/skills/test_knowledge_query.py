"""知识查询 Skill 测试"""

import pytest

from skills.knowledge_query import KnowledgeQuerySkill


class MockVectorStore:

    def search(self, query, n_results=5):
        return [
            {"text": "PA 核心装备：狂战斧、黑皇杖、黯灭", "metadata": {"hero": "phantom_assassin"}},
            {"text": "PA 前期可选相位鞋", "metadata": {"hero": "phantom_assassin"}},
        ]


class MockFusionEngine:

    def merge(self, structured_knowledge, unstructured_knowledge, query):
        class Result:
            def to_dict(self):
                return {
                    "answer": "PA 推荐出装：狂战斧、黑皇杖、黯灭",
                    "sources": [{"hero": "phantom_assassin"}],
                }
        return Result()


@pytest.mark.asyncio
async def test_knowledge_query_success(mock_llm):
    skill = KnowledgeQuerySkill(
        llm_client=mock_llm,
        vector_store=MockVectorStore(),
        fusion_engine=MockFusionEngine(),
    )
    result = await skill.run("PA 怎么出装？")

    assert result.success is True
    assert "answer" in result.data
    assert len(result.data["sources"]) == 1
    assert result.confidence == 0.85


@pytest.mark.asyncio
async def test_knowledge_query_empty_results(mock_llm):
    class EmptyVectorStore:
        def search(self, query, n_results=5):
            return []

    skill = KnowledgeQuerySkill(
        llm_client=mock_llm,
        vector_store=EmptyVectorStore(),
    )
    result = await skill.run("不存在的查询")

    assert result.success is True
    assert result.confidence == 0.4


@pytest.mark.asyncio
async def test_knowledge_query_fallback(mock_llm):
    skill = KnowledgeQuerySkill(
        llm_client=mock_llm,
        vector_store=MockVectorStore(),
        fusion_engine=MockFusionEngine(),
    )
    result = await skill._fallback("PA 怎么出装？")

    assert result.success is True
    assert "暂不可用" in result.data["answer"]
    assert result.confidence == 0.2
