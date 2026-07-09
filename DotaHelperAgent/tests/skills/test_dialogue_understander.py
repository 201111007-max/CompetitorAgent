"""多轮对话理解 Skill 测试"""

import pytest

from skills.dialogue_understander import DialogueUnderstanderSkill


class MockContextAugmenter:

    def augment_query(self, query, session):
        return {
            "augmented_query": f"增强后的{query}",
            "inferred_intent": "recommend_heroes",
            "entities": [{"type": "hero", "name": "pudge"}],
            "context": {"conversation_history": [{"role": "user", "content": "hello"}]},
        }


@pytest.mark.asyncio
async def test_dialogue_understander_json_parsing(mock_llm_json):
    skill = DialogueUnderstanderSkill(llm_client=mock_llm_json)
    result = await skill.run({
        "history": [{"role": "user", "content": "推荐英雄"}],
        "current_input": "PA 怎么出装",
    })

    assert result.success is True
    assert result.data["key"] == "value"


@pytest.mark.asyncio
async def test_dialogue_understander_fallback(mock_llm):
    augmenter = MockContextAugmenter()
    skill = DialogueUnderstanderSkill(
        llm_client=mock_llm,
        context_augmenter=augmenter,
    )

    # 直接测试 _fallback 路径
    result = await skill._fallback({
        "history": [{"role": "user", "content": "推荐英雄"}],
        "current_input": "PA 怎么出装",
    })

    assert result.success is True
    assert result.data["intent"] == "recommend_heroes"
    assert "PA 怎么出装" in result.data["enhanced_query"]
    assert result.fallback_used is False


@pytest.mark.asyncio
async def test_dialogue_understander_no_augmenter_fallback(mock_llm):
    skill = DialogueUnderstanderSkill(llm_client=mock_llm)

    result = await skill._fallback({
        "history": [],
        "current_input": "hello",
    })

    assert result.success is True
    assert result.data["intent"] == "general"
    assert result.data["context_used"] is False
