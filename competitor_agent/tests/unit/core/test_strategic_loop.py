"""core/strategic_loop.py + competitor_registry.py 单测（设计文档 47：仅 LLM 规划）"""
import json
import pytest

from competitor_agent.core.competitor_registry import COMPETITOR_REGISTRY, resolve_competitor
from competitor_agent.core.strategic_loop import StrategicPlanner
from competitor_agent.domain_types import DimensionType, GapStatus
from competitor_agent.evaluation.benchmark import BenchmarkMockLLM
from competitor_agent.interfaces.context import Skill
from competitor_agent.llm.client import LLMClient


class TestCompetitorRegistry:
    def test_resolve_registered(self):
        c = resolve_competitor("Claude Code")
        assert c.name == "claude-code"
        assert "pricing" in c.official_links

    def test_resolve_by_alias(self):
        c = resolve_competitor("github copilot")
        assert c.name == "copilot"

    def test_resolve_unknown_raises_value_error(self):
        """设计文档 47：未命中注册表抛 ValueError（不再 ASCII 造竞品）。"""
        with pytest.raises(ValueError):
            resolve_competitor("SomeNewAgent")

    def test_resolve_unknown_chinese_raises_value_error(self):
        with pytest.raises(ValueError):
            resolve_competitor("分析 New Tool")

    def test_registry_contains_common(self):
        assert "cursor" in COMPETITOR_REGISTRY
        assert "codex" in COMPETITOR_REGISTRY


class TestStrategicPlanner:
    def _mock(self, competitor: str = "", budget: dict | None = None) -> LLMClient:
        mock = BenchmarkMockLLM(competitor=competitor)
        payload = {"competitor": competitor or "cursor", "dimensions": []}
        if budget:
            payload["budget"] = budget
        return LLMClient(call_func=lambda messages, model: json.dumps(payload))

    def test_plan_basic(self):
        p = StrategicPlanner(llm=self._mock("claude-code"), use_llm=True)
        strategy = p.plan("分析 Claude Code")
        assert strategy.competitor.name == "claude-code"
        assert len(strategy.gaps) == 6
        # 全部缺口初始为 OPEN
        assert all(g.status == GapStatus.OPEN for g in strategy.gaps)

    def test_gap_priorities_default(self):
        p = StrategicPlanner(llm=self._mock("cursor"), use_llm=True)
        strategy = p.plan("分析 cursor")
        by_field = {g.field: g for g in strategy.gaps}
        assert by_field["pricing"].priority == 9
        assert by_field["feature"].priority == 8
        assert by_field["roadmap"].priority == 4

    def test_budget_allocation_from_llm(self):
        p = StrategicPlanner(llm=self._mock("cursor", budget={"pricing": 2, "feature": 3}), use_llm=True)
        strategy = p.plan("cursor")
        assert strategy.budget_allocation[DimensionType.PRICING] == 2
        assert strategy.budget_allocation[DimensionType.FEATURE] == 3

    def test_no_llm_raises(self):
        with pytest.raises(Exception):
            StrategicPlanner().plan("cursor")

    def test_memory_boost(self):
        class MemoryWithSkill:
            def retrieve_skills(self, name):
                return [Skill(competitor_name="cursor", gap_field="pricing", source_name="docs", success=True)]

            def archive_session(self, session): ...
            def save_note(self, competitor, note): ...
            def retrieve_notes(self, competitor): return []
            def record_skill(self, skill): ...
            def record_outcome(self, source, success): ...
            def source_success_rates(self): return {}

        p = StrategicPlanner(llm=self._mock("cursor"), use_llm=True)
        strategy = p.plan("cursor", memory=MemoryWithSkill())
        by_field = {g.field: g for g in strategy.gaps}
        assert by_field["pricing"].confidence == 0.2

    def test_memory_error_does_not_break(self):
        class BrokenMemory:
            def retrieve_skills(self, name):
                raise RuntimeError("boom")

        p = StrategicPlanner(llm=self._mock("cursor"), use_llm=True)
        strategy = p.plan("cursor", memory=BrokenMemory())
        assert len(strategy.gaps) == 6
