"""设计文档 44：规划 LLM 化单测（StrategicPlanner 结构化规划 + 规则兜底）

- LLM 结构化规划（competitor/dimensions/priorities/budget/custom_sources）入 CompetitorStrategy
- 非法枚举 / budget 缺失 → 兜底（缺失维度默认 1 / 非法回退规则版）
- use_llm=False 纯规则结果与现状一致；记忆提权在 LLM 路径同样生效
"""
from __future__ import annotations

import json

from competitor_agent.core.strategic_loop import StrategicPlanner
from competitor_agent.domain_types import DimensionType, GapStatus
from competitor_agent.interfaces.context import Skill
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

    def test_invalid_enum_falls_back_to_rules(self):
        llm = _plan_llm({"competitor": "Cursor", "dimensions": ["pricing", "bogus_dim"]})
        strategy = StrategicPlanner(llm=llm, use_llm=True).plan("Cursor")
        # bogus_dim 不在枚举 → complete_json schema 失败 → 回退规则版（默认 6 维度）
        assert len(strategy.gaps) == 6

    def test_empty_competitor_falls_back_to_rules(self):
        llm = _plan_llm({"competitor": "", "dimensions": ["pricing"]})
        strategy = StrategicPlanner(llm=llm, use_llm=True).plan("分析 Cursor")
        # competitor 空 → _strategy_from_llm 抛错 → 回退规则版
        assert strategy.competitor.name == "cursor"
        assert len(strategy.gaps) == 6

    def test_missing_competitor_key_schema_fails_to_rules(self):
        llm = _plan_llm({"dimensions": ["pricing"]})  # 缺 required competitor
        strategy = StrategicPlanner(llm=llm, use_llm=True).plan("Cursor")
        assert len(strategy.gaps) == 6

    def test_llm_memory_boost_applied(self):
        """LLM 规划结果同样走 _apply_memory_boost：技能命中的缺口置信度 +0.2。"""
        llm = _plan_llm({"competitor": "Cursor", "dimensions": ["pricing", "feature"]})
        memory = StubMemory(
            skills=[Skill(competitor_name="cursor", gap_field="pricing", source_name="docs", success=True)]
        )
        strategy = StrategicPlanner(llm=llm, use_llm=True).plan("Cursor", memory=memory)
        by_field = {g.field: g for g in strategy.gaps}
        assert by_field["pricing"].confidence == 0.2

    def test_plan_prompt_contains_memory_context(self):
        captured = []

        def rec(messages, model):
            captured.append(messages)
            return json.dumps({"competitor": "Cursor", "dimensions": ["pricing"]})

        planner = StrategicPlanner(llm=LLMClient(call_func=rec), use_llm=True)
        planner.plan("Cursor", memory=StubMemory())
        assert "历史：pricing 用官网源有效" in captured[0][0]["content"]


class TestRulesFallback:
    def test_use_llm_false_uses_rules(self):
        """use_llm=False（即使给了 llm）→ 纯规则，行为与现状一致。"""
        llm = LLMClient(call_func=lambda m, x: json.dumps({"competitor": "Cursor"}))
        p = StrategicPlanner(llm=llm, use_llm=False)
        strategy = p.plan("分析 cursor 的定价 pricing")
        by_field = {g.field: g for g in strategy.gaps}
        assert len(strategy.gaps) == 6
        assert by_field["pricing"].priority == 10  # 关键词提权
        assert strategy.budget_allocation[DimensionType.FEATURE] == 3

    def test_rules_path_budget_allocation(self):
        p = StrategicPlanner()
        strategy = p.plan("cursor")
        assert strategy.budget_allocation[DimensionType.PRICING] == 2
        assert strategy.budget_allocation[DimensionType.FEATURE] == 3
