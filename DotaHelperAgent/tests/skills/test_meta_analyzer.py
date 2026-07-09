"""版本强势查询 Skill 测试"""

import pytest

from skills.meta_analyzer import MetaAnalyzerSkill


async def mock_fetch_meta():
    return {
        "meta_heroes": [
            {"hero_name": "pudge", "win_rate": 0.55, "pick_rate": 0.30},
            {"hero_name": "axe", "win_rate": 0.53, "pick_rate": 0.25},
        ]
    }


@pytest.mark.asyncio
async def test_meta_analyzer_success(mock_llm):
    skill = MetaAnalyzerSkill(
        llm_client=mock_llm,
        data_fetcher=mock_fetch_meta,
    )
    result = await skill.run("当前版本哪些英雄强势？")

    assert result.success is True
    assert "answer" in result.data
    assert len(result.data["meta_heroes"]) == 2
    assert result.confidence == 0.8


@pytest.mark.asyncio
async def test_meta_analyzer_fallback(mock_llm):
    skill = MetaAnalyzerSkill(
        llm_client=mock_llm,
        data_fetcher=mock_fetch_meta,
    )
    result = await skill._fallback("当前版本哪些英雄强势？")

    assert result.success is True
    assert "pudge" in result.data["answer"]
    assert "axe" in result.data["answer"]
    assert result.confidence == 0.4


@pytest.mark.asyncio
async def test_meta_analyzer_cache(mock_llm):
    skill = MetaAnalyzerSkill(
        llm_client=mock_llm,
        data_fetcher=mock_fetch_meta,
        cache_ttl=3600,
    )
    await skill.run("当前版本哪些英雄强势？")
    # 第二次调用应使用缓存
    assert skill._cache is not None
    assert len(skill._cache["meta_heroes"]) == 2
