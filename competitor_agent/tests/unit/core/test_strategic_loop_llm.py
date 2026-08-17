"""设计文档 44/47：规划 LLM 化单测（StrategicPlanner 结构化规划，仅 LLM）

- LLM 结构化规划（competitor/dimensions/priorities/budget/custom_sources）入 CompetitorStrategy
- 非法枚举 / 缺失字段 / 空 competitor → 抛错（设计文档 47：不再回退规则版）
- 记忆提权在 LLM 路径生效；规划 prompt 含任务 + 历史经验
"""
from __future__ import annotations

import json

import pytest

from competitor_agent.core.strategic_loop import StrategicPlanner
from competitor_agent.domain_types import DimensionType, GapStatus
from competitor_agent.interfaces.context import Skill
from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.llm.client import LLMClient


def _plan_llm(payload):
    return LLMClient(call_func=lambda messages, model: json.dumps(payload))


class StubMemory:
    """实现 LLM 规划路径用到的记忆协议方法（技能 + L4 模式 + recent_context）。"""

    def __init__(self, skills=None):
        self._skills = skills or []

    def retrieve_skills(self, name):
        return self._skills

    def retrieve_patterns_with_outcome(self, competitor, dimension):
        return []

    def recent_context(self, competitor, top_k=3, query=""):
        return ["历史：pricing 用官网源有效"]


class TestLlmPlanning:
    def test_full_llm_plan_into_strategy(self):
        llm = _plan_llm(
            {
                "competitor": "Cursor",
                "dimensions": ["pricing", "performance"],
                "priorities": {"pricing": 10, "performance": 6},
                "budget": {"pricing": 3, "performance": 2},
                "custom_sources": {"pricing": "https://cursor.example/pricing"},
            }
        )
        strategy = StrategicPlanner(llm=llm, use_llm=True).plan("分析 Cursor 的定价和性能")
        assert strategy.competitor.name == "cursor"
        assert [g.field for g in strategy.gaps] == ["pricing", "performance"]
        by_field = {g.field: g for g in strategy.gaps}
        assert by_field["pricing"].priority == 10
        assert by_field["performance"].priority == 6
        assert strategy.budget_allocation[DimensionType.PRICING] == 3
        assert strategy.budget_allocation[DimensionType.PERFORMANCE] == 2
        assert strategy.competitor.official_links["pricing"] == "https://cursor.example/pricing"
        assert all(g.status == GapStatus.OPEN for g in strategy.gaps)

    def test_missing_budget_defaults_to_one(self):
        llm = _plan_llm({"competitor": "Cursor", "dimensions": ["pricing"], "budget": {}})
        strategy = StrategicPlanner(llm=llm, use_llm=True).plan("Cursor")
        assert strategy.budget_allocation[DimensionType.PRICING] == 1

    def test_priorities_budget_out_of_range_coerced(self):
        llm = _plan_llm(
            {
                "competitor": "Cursor",
                "dimensions": ["pricing"],
                "priorities": {"pricing": 99},
                "budget": {"pricing": 100},
            }
        )
        strategy = StrategicPlanner(llm=llm, use_llm=True).plan("Cursor")
        by_field = {g.field: g for g in strategy.gaps}
        assert by_field["pricing"].priority == 10  # 收敛上限
        assert strategy.budget_allocation[DimensionType.PRICING] == 5  # 收敛上限

    def test_invalid_enum_schema_fails(self):
        """非法维度枚举 → complete_json schema 校验失败 → LLMUnavailableError。"""
        llm = _plan_llm({"competitor": "Cursor", "dimensions": ["pricing", "bogus_dim"]})
        with pytest.raises(LLMUnavailableError):
            StrategicPlanner(llm=llm, use_llm=True).plan("Cursor")

    def test_empty_competitor_raises(self):
        """空 competitor → _strategy_from_llm 抛错（不再回退规则版）。"""
        llm = _plan_llm({"competitor": "", "dimensions": ["pricing"]})
        with pytest.raises(ValueError):
            StrategicPlanner(llm=llm, use_llm=True).plan("分析 Cursor")

    def test_missing_competitor_key_schema_fails(self):
        llm = _plan_llm({"dimensions": ["pricing"]})  # 缺 required competitor
        with pytest.raises(LLMUnavailableError):
            StrategicPlanner(llm=llm, use_llm=True).plan("Cursor")

    def test_llm_memory_boost_applied(self):
        """LLM 规划结果同样走 _apply_memory_boost：技能命中的缺口置信度 +0.2。"""
        llm = _plan_llm({"competitor": "Cursor", "dimensions": ["pricing", "feature"]})
        memory = StubMemory(
            skills=[Skill(competitor_name="cursor", gap_field="pricing", source_name="docs", success=True)]
        )
        strategy = StrategicPlanner(llm=llm, use_llm=True).plan("Cursor", memory=memory)
        by_field = {g.field: g for g in strategy.gaps}
        assert by_field["pricing"].confidence == 0.2

    def test_plan_prompt_contains_task_and_memory_context(self):
        captured = []

        def rec(messages, model):
            captured.append(messages)
            system = messages[0].get("content", "")
            if "语义解析器" in system:
                # 记忆预判的 parse 调用：返回竞品
                return json.dumps({"competitors": ["cursor"], "dimensions": None, "custom_sources": {}})
            return json.dumps({"competitor": "Cursor", "dimensions": ["pricing"]})

        planner = StrategicPlanner(llm=LLMClient(call_func=rec), use_llm=True)
        planner.plan("分析 Cursor", memory=StubMemory())
        plan_prompt = captured[-1][0]["content"]
        assert "分析 Cursor" in plan_prompt  # 用户任务在规划 prompt 中
        assert "历史：pricing 用官网源有效" in plan_prompt


class TestNoLlmRaises:
    def test_use_llm_false_raises(self):
        """设计文档 47：use_llm=False 直接抛 LLMUnavailableError（无规则版）。"""
        llm = LLMClient(call_func=lambda m, x: json.dumps({"competitor": "Cursor"}))
        p = StrategicPlanner(llm=llm, use_llm=False)
        with pytest.raises(LLMUnavailableError):
            p.plan("分析 cursor 的定价 pricing")

    def test_no_llm_raises(self):
        p = StrategicPlanner()
        with pytest.raises(LLMUnavailableError):
            p.plan("cursor")
