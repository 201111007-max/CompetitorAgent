"""阵容分析 Skill 测试"""

import pytest

from skills.base import SkillResult
from skills.lineup_analyzer import LineupAnalyzerSkill


class MockHeroAnalyzer:

    def analyze_team_composition(self, radiant, dire):
        return {
            "our_advantages": ["控制足"],
            "enemy_advantages": ["爆发高"],
            "overall_advantage": 0.6,
            "conclusion": "己方阵容略优",
        }


@pytest.mark.asyncio
async def test_lineup_analyzer_success(mock_llm):
    skill = LineupAnalyzerSkill(
        llm_client=mock_llm,
        hero_analyzer=MockHeroAnalyzer(),
    )
    result = await skill.run({
        "radiant_heroes": ["pudge", "axe"],
        "dire_heroes": ["zeus", "crystal_maiden"],
    })

    assert result.success is True
    assert "analysis" in result.data
    assert result.data["structured"]["conclusion"] == "己方阵容略优"
    assert result.confidence == 0.85


@pytest.mark.asyncio
async def test_lineup_analyzer_fallback_without_analyzer(mock_llm):
    skill = LineupAnalyzerSkill(llm_client=mock_llm)
    # 让主逻辑失败：没有 analyzer 但 prompt_manager 也没有，不会失败
    # 这里测试降级路径：传入空数据
    result = await skill._fallback({"radiant_heroes": [], "dire_heroes": []})

    assert isinstance(result, SkillResult)
    assert result.success is True
    assert "暂不可用" in result.data["analysis"]
    assert result.confidence == 0.3
