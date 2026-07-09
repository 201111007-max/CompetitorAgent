"""SkillRegistry 测试"""

import pytest

from skills import get_registry
from skills.base import BaseSkill, SkillResult
from skills.exceptions import SkillExecutionError
from skills.registry import SkillRegistry


class DummySkill(BaseSkill):

    async def execute(self, input_data, context=None):
        return SkillResult(success=True, data={"input": input_data})

    async def _fallback(self, input_data, context=None, error=None):
        return SkillResult(success=True, data={"fallback": True})


def test_registry_singleton():
    r1 = get_registry()
    r2 = get_registry()
    assert r1 is r2


def test_registry_register_and_get():
    registry = SkillRegistry()
    registry._skills.clear()

    skill = DummySkill(name="dummy")
    registry.register(skill)

    assert registry.get("dummy") is skill
    assert "dummy" in registry.list_all()


def test_registry_duplicate_registration():
    registry = SkillRegistry()
    registry._skills.clear()

    registry.register(DummySkill(name="dup"))
    with pytest.raises(ValueError):
        registry.register(DummySkill(name="dup"))


def test_registry_unregister():
    registry = SkillRegistry()
    registry._skills.clear()

    registry.register(DummySkill(name="remove_me"))
    registry.unregister("remove_me")

    assert registry.get("remove_me") is None


@pytest.mark.asyncio
async def test_registry_invoke_success():
    registry = SkillRegistry()
    registry._skills.clear()

    registry.register(DummySkill(name="invokable"))
    result = await registry.invoke("invokable", "hello")

    assert result.success is True
    assert result.data["input"] == "hello"


@pytest.mark.asyncio
async def test_registry_invoke_not_found():
    registry = SkillRegistry()
    registry._skills.clear()

    with pytest.raises(SkillExecutionError):
        await registry.invoke("missing", "hello")


@pytest.mark.asyncio
async def test_registry_invoke_disabled():
    registry = SkillRegistry()
    registry._skills.clear()

    skill = DummySkill(name="disabled")
    skill.disable()
    registry.register(skill)

    with pytest.raises(SkillExecutionError):
        await registry.invoke("disabled", "hello")
