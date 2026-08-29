"""设计文档 70 M2 — 规划层意图/格式决策单测。

覆盖：
① PLAN_SCHEMA 增三个可选字段（output_intent/format_hint/need_history），
   make_plan 校验通过且原样回传；
② 兼容旧 plan（无新字段）→ 校验仍通过（只定调不强制）；
③ Lead 系统提示两段式 Final Answer + M2 字段说明（正文+JSON、reuse_dimension_results 提示）。
"""
from __future__ import annotations

import json

from competitor_agent.agent.make_plan import make_plan
from competitor_agent.agent.prompts.react_system import build_lead_system_prompt
from competitor_agent.agent.react_schemas import PLAN_SCHEMA


class TestPlanSchemaFields:
    def test_schema_has_m2_optional_fields(self) -> None:
        props = PLAN_SCHEMA["properties"]
        assert "output_intent" in props
        assert "format_hint" in props
        assert "need_history" in props
        assert props["need_history"]["type"] == "boolean"

    def test_make_plan_accepts_m2_fields(self) -> None:
        result = make_plan(json.dumps({
            "competitor": "cursor",
            "output_intent": "CTO 选型",
            "format_hint": "对比型",
            "need_history": True,
        }, ensure_ascii=False))
        plan = json.loads(result)
        assert plan["output_intent"] == "CTO 选型"
        assert plan["format_hint"] == "对比型"
        assert plan["need_history"] is True

    def test_make_plan_accepts_old_plan_without_m2(self) -> None:
        result = make_plan(json.dumps({"competitor": "cursor"}, ensure_ascii=False))
        assert result.startswith("make_plan") is False

    def test_make_plan_rejects_bad_need_history_type(self) -> None:
        result = make_plan(json.dumps({"competitor": "cursor", "need_history": "yes"}, ensure_ascii=False))
        assert result.startswith("make_plan 校验失败")


class TestLeadPromptM1M2:
    def test_prompt_has_two_part_final_answer(self) -> None:
        prompt = build_lead_system_prompt()
        assert "① 报告正文" in prompt
        assert "② 结构化数据" in prompt
        assert "只输出一份 JSON" in prompt
        assert "两者缺一不可" in prompt

    def test_prompt_mentions_m2_fields_and_reuse_tool(self) -> None:
        prompt = build_lead_system_prompt()
        assert "output_intent" in prompt
        assert "format_hint" in prompt
        assert "need_history" in prompt
        assert "reuse_dimension_results" in prompt
        assert "as_of" in prompt
