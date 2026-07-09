"""智能搜索 Skill 测试"""

import pytest

from skills.web_search import WebSearchSkill


class MockSearchEngine:

    def search(self, query, max_results=5):
        return [
            {"title": "PA 攻略", "body": "PA 是强力核心", "href": "http://example.com/pa"},
        ]


@pytest.mark.asyncio
async def test_web_search_success(mock_llm):
    skill = WebSearchSkill(
        llm_client=mock_llm,
        search_engine=MockSearchEngine(),
    )
    result = await skill.run("PA 攻略")

    assert result.success is True
    assert "answer" in result.data
    assert len(result.data["sources"]) == 1
    assert result.data["sources"][0]["url"] == "http://example.com/pa"
    assert result.confidence == 0.75


@pytest.mark.asyncio
async def test_web_search_empty_results(mock_llm):
    class EmptyEngine:
        def search(self, query, max_results=5):
            return []

    skill = WebSearchSkill(
        llm_client=mock_llm,
        search_engine=EmptyEngine(),
    )
    result = await skill.run("不存在的查询")

    assert result.success is True
    assert result.confidence == 0.3


@pytest.mark.asyncio
async def test_web_search_fallback(mock_llm):
    skill = WebSearchSkill(
        llm_client=mock_llm,
        search_engine=MockSearchEngine(),
    )
    result = await skill._fallback("PA 攻略")

    assert result.success is True
    assert "暂不可用" in result.data["answer"]
    assert result.confidence == 0.2
