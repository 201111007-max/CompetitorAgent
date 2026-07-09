"""Skill 测试 fixtures"""

import pytest

from skills.base import SkillContext


class MockLLMClient:
    """模拟 LLM 客户端"""

    def __init__(self, response: str = "mock response") -> None:
        self.response = response

    def complete(self, prompt: str) -> str:
        return self.response


@pytest.fixture
def mock_llm():
    return MockLLMClient()


@pytest.fixture
def mock_llm_json():
    return MockLLMClient(response='{"key": "value"}')


@pytest.fixture
def skill_context():
    return SkillContext(session_id="test_session", user_id="test_user")
