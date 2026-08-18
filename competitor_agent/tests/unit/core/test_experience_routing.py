"""经验路由委派测试（设计文档 49 §3.5）

按 L4 模式排序缺口执行顺序：成功模式维度提前、失败/降级反例维度后置；
同时 _apply_pattern_boost 对失败反例维度优先级 -1（仅未定置信缺口）。
纯排序不改变缺口集合与 LLM 调用结构；无经验/未启用 → 顺序不变。
"""
from __future__ import annotations

from competitor_agent.core.strategic_loop import StrategicPlanner


class StubMemory:
    """带 L4 模式（pattern, outcome）的存根记忆。"""

    def __init__(self, patterns: dict[str, list[str]] | None = None):
        self._patterns = patterns or {}

    def retrieve_patterns_with_outcome(self, competitor, dimension):
        return [(f"p-{dimension}-{i}", o) for i, o in enumerate(self._patterns.get(dimension, []))]

    def retrieve_skills(self, name):
        return []

    def recent_context(self, competitor, top_k=3, query=""):
        return []


def _gaps(*fields: str):
    """构造按原顺序的 gap 列表（field 依次为 pricing/feature/...）。"""
    from competitor_agent.domain_types.info_gap import InfoGap

    return [InfoGap(field=f, priority=5, confidence=0.0) for f in fields]


def _competitor():
    from competitor_agent.domain_types.competitor import Competitor

    return Competitor(name="cursor")


def _ordered(planner, memory, gaps):
    """走完整 _strategy_from_llm 前的排序路径：先 boost 再排序。"""
    competitor = _competitor()
    planner._apply_memory_boost(gaps, competitor, memory)
    planner._apply_pattern_boost(gaps, competitor, memory)
    return planner._order_gaps_by_experience(gaps, competitor, memory)


class TestExperienceOrdering:
    def test_success_dimension_ordered_first(self):
        planner = StrategicPlanner()
        memory = StubMemory(
            {
                "pricing": ["success", "success"],
                "feature": ["failure"],
            }
        )
        ordered = _ordered(planner, memory, _gaps("feature", "pricing"))
        assert [g.field for g in ordered] == ["pricing", "feature"]

    def test_no_experience_keeps_order(self):
        planner = StrategicPlanner()
        ordered = _ordered(planner, StubMemory(), _gaps("feature", "pricing"))
        assert [g.field for g in ordered] == ["feature", "pricing"]

    def test_disabled_routing_keeps_order(self):
        planner = StrategicPlanner(experience_routing=False)
        memory = StubMemory({"pricing": ["success"], "feature": ["failure"]})
        ordered = planner._order_gaps_by_experience(_gaps("feature", "pricing"), _competitor(), memory)
        assert [g.field for g in ordered] == ["feature", "pricing"]

    def test_stable_sort_preserves_ties(self):
        planner = StrategicPlanner()
        memory = StubMemory()  # 全部无经验 → 全 0 分，保持原顺序
        gaps = _gaps("pricing", "feature", "performance")
        ordered = planner._order_gaps_by_experience(gaps, _competitor(), memory)
        assert [g.field for g in ordered] == ["pricing", "feature", "performance"]

    def test_same_gap_set_not_modified(self):
        planner = StrategicPlanner()
        memory = StubMemory({"pricing": ["success"], "feature": ["failure"]})
        original = _gaps("feature", "pricing")
        ordered = _ordered(planner, memory, original)
        assert set(g.field for g in ordered) == {"feature", "pricing"}


class TestPatternBoost:
    def test_success_boost_confidence(self):
        planner = StrategicPlanner()
        memory = StubMemory({"pricing": ["success"]})
        gaps = _gaps("pricing")
        planner._apply_pattern_boost(gaps, _competitor(), memory)
        assert gaps[0].confidence == 0.1

    def test_failure_degrades_priority_of_undecided_gap(self):
        planner = StrategicPlanner()
        memory = StubMemory({"pricing": ["failure"]})
        gaps = _gaps("pricing")
        planner._apply_pattern_boost(gaps, _competitor(), memory)
        assert gaps[0].priority == 4  # 5 - 1

    def test_failure_does_not_degrade_decided_gap(self):
        planner = StrategicPlanner()
        memory = StubMemory({"pricing": ["failure"]})
        from competitor_agent.domain_types.info_gap import InfoGap

        gaps = [InfoGap(field="pricing", priority=5, confidence=0.5)]
        planner._apply_pattern_boost(gaps, _competitor(), memory)
        assert gaps[0].priority == 5  # 已有置信不降权
