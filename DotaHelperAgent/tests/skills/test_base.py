"""Skill 基类测试"""

import pytest

from skills.base import BaseSkill, SkillContext, SkillResult
from skills.exceptions import SkillExecutionError


class SuccessSkill(BaseSkill):
    """总是成功的测试 Skill"""

    async def execute(self, input_data, context=None):
        return SkillResult(success=True, data={"value": input_data})

    async def _fallback(self, input_data, context=None, error=None):
        return SkillResult(success=True, data={"fallback": True})


class FailSkill(BaseSkill):
    """主逻辑失败但降级成功的测试 Skill"""

    async def execute(self, input_data, context=None):
        raise RuntimeError("main failed")

    async def _fallback(self, input_data, context=None, error=None):
        return SkillResult(success=True, data={"fallback": True})


class DoubleFailSkill(BaseSkill):
    """主逻辑和降级都失败的测试 Skill"""

    async def execute(self, input_data, context=None):
        raise RuntimeError("main failed")

    async def _fallback(self, input_data, context=None, error=None):
        raise RuntimeError("fallback failed")


class TimeoutSkill(BaseSkill):
    """超时的测试 Skill"""

    def __init__(self):
        super().__init__(name="timeout", timeout=0.01)

    async def execute(self, input_data, context=None):
        import asyncio
        await asyncio.sleep(1)
        return SkillResult(success=True, data={})

    async def _fallback(self, input_data, context=None, error=None):
        return SkillResult(success=True, data={"fallback": True})


@pytest.mark.asyncio
async def test_success_skill_run():
    skill = SuccessSkill(name="success")
    result = await skill.run("test")

    assert result.success is True
    assert result.data["value"] == "test"
    assert result.fallback_used is False


@pytest.mark.asyncio
async def test_fallback_on_execute_failure():
    skill = FailSkill(name="fail")
    result = await skill.run("test")

    assert result.success is True
    assert result.data["fallback"] is True
    assert result.fallback_used is True


@pytest.mark.asyncio
async def test_double_failure_raises():
    skill = DoubleFailSkill(name="double_fail")
    with pytest.raises(SkillExecutionError):
        await skill.run("test")


@pytest.mark.asyncio
async def test_timeout_triggers_fallback():
    skill = TimeoutSkill()
    result = await skill.run("test")

    assert result.success is True
    assert result.data["fallback"] is True
    assert result.fallback_used is True


def test_skill_enable_disable():
    skill = SuccessSkill(name="toggle")
    assert skill.enabled is True

    skill.disable()
    assert skill.enabled is False

    skill.enable()
    assert skill.enabled is True


def test_skill_context_to_dict():
    ctx = SkillContext(session_id="s1", user_id="u1", trace_id="t1")
    d = ctx.to_dict()

    assert d["session_id"] == "s1"
    assert d["user_id"] == "u1"
    assert d["trace_id"] == "t1"


def test_skill_result_to_dict():
    result = SkillResult(success=True, data={"x": 1}, confidence=0.9)
    d = result.to_dict()

    assert d["success"] is True
    assert d["data"] == {"x": 1}
    assert d["confidence"] == 0.9
    assert d["fallback_used"] is False
