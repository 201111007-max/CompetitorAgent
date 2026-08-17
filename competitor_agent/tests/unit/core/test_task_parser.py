"""core/task_parser.py 单测（设计文档 47：仅 LLM 解析，无规则降级）"""
import json

import pytest

from competitor_agent.core.task_parser import ResolutionDecision, TaskParseResult, parse_task
from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.llm.client import LLMClient


class TestParseTaskLLM:
    def test_llm_parses_struct(self):
        llm = LLMClient(
            call_func=lambda messages, model: json.dumps(
                {"resolution": "registry", "competitors": ["cursor"], "dimensions": ["pricing"], "custom_sources": {}}
            )
        )
        result = parse_task("分析 Cursor", llm=llm, use_llm=True)
        assert result.competitors == ["cursor"]
        assert result.dimensions == ["pricing"]
        assert result.raw_task == "分析 Cursor"

    def test_llm_garbage_raises_llm_unavailable(self):
        llm = LLMClient(call_func=lambda messages, model: "不是 JSON")
        with pytest.raises(LLMUnavailableError):
            parse_task("只分析 Cursor 定价", llm=llm, use_llm=True)

    def test_no_llm_raises(self):
        with pytest.raises(LLMUnavailableError):
            parse_task("对比 Cursor 和 Windsurf", llm=None, use_llm=True)

    def test_use_llm_false_raises(self):
        llm = LLMClient(call_func=lambda messages, model: "{}")
        with pytest.raises(LLMUnavailableError):
            parse_task("分析 Cursor", llm=llm, use_llm=False)

    def test_empty_competitors_returns_unknown_primary(self):
        llm = LLMClient(
            call_func=lambda messages, model: json.dumps(
                {"resolution": "discovery", "competitors": [], "dimensions": None, "custom_sources": {}}
            )
        )
        result = parse_task("帮我找所有 agent", llm=llm, use_llm=True)
        assert result.primary_competitor == "unknown"
        assert result.is_discovery

    def test_invalid_dimensions_filtered(self):
        """非法维度名被过滤；全部非法 → None（全部维度）。"""
        llm = LLMClient(
            call_func=lambda messages, model: json.dumps(
                {"competitors": ["cursor"], "dimensions": ["pricing", "bogus"], "custom_sources": {}}
            )
        )
        result = parse_task("分析 Cursor", llm=llm, use_llm=True)
        assert result.dimensions == ["pricing"]

    def test_llm_failure_propagates(self):
        class FailingLLM(LLMClient):
            def complete(self, messages, json_mode=False):
                raise RuntimeError("llm down")

        with pytest.raises(LLMUnavailableError):
            parse_task("分析 Cursor", llm=FailingLLM(), use_llm=True)


class TestResolutionDecision:
    """设计文档 20：LLM 输出 resolution 决策（REGISTRY / DISCOVERY / COMPARE）"""

    @staticmethod
    def _llm(payload: dict) -> LLMClient:
        return LLMClient(call_func=lambda messages, model: json.dumps(payload))

    def test_llm_discovery_sets_is_discovery(self):
        result = parse_task(
            "帮我找市场上所有 AI coding agent",
            llm=self._llm({"resolution": "discovery", "competitors": [], "dimensions": None, "custom_sources": {}}),
            use_llm=True,
        )
        assert result.resolution == ResolutionDecision.DISCOVERY
        assert result.is_discovery

    def test_llm_registry_sets_not_discovery(self):
        result = parse_task(
            "分析 Cursor",
            llm=self._llm({"resolution": "registry", "competitors": ["cursor"], "dimensions": None, "custom_sources": {}}),
            use_llm=True,
        )
        assert result.resolution == ResolutionDecision.REGISTRY
        assert not result.is_discovery

    def test_llm_compare_three_names(self):
        result = parse_task(
            "对比 Cursor 和 Windsurf 和 Copilot",
            llm=self._llm(
                {"resolution": "compare", "competitors": ["cursor", "windsurf", "copilot"], "dimensions": None, "custom_sources": {}}
            ),
            use_llm=True,
        )
        assert result.resolution == ResolutionDecision.COMPARE
        assert len(result.competitors) == 3
        assert result.is_compare

    def test_llm_bad_resolution_defaults_registry(self):
        """畸形 resolution → 默认 REGISTRY（不做规则推断）。"""
        result = parse_task(
            "分析 Cursor",
            llm=self._llm({"resolution": "totally-wrong", "competitors": ["cursor"], "dimensions": None, "custom_sources": {}}),
            use_llm=True,
        )
        assert result.resolution == ResolutionDecision.REGISTRY


class TestStrategicLoopDimensions:
    """设计文档 47：规划走 LLM 版 parse_task（mock LLM 断言）"""

    def test_dimension_whitelist_restricts_gaps(self):
        from competitor_agent.core.strategic_loop import StrategicPlanner

        llm = LLMClient(
            call_func=lambda messages, model: json.dumps(
                {"competitor": "cursor", "dimensions": ["pricing"], "priorities": {}, "budget": {}}
            )
        )
        planner = StrategicPlanner(llm=llm, use_llm=True)
        strategy = planner.plan("只分析 Cursor 定价")
        assert [g.field for g in strategy.gaps] == ["pricing"]

    def test_custom_source_merged_into_links(self):
        from competitor_agent.core.strategic_loop import StrategicPlanner

        llm = LLMClient(
            call_func=lambda messages, model: json.dumps(
                {"competitor": "cursor", "dimensions": None, "custom_sources": {"home": "https://custom.example.com"}}
            )
        )
        planner = StrategicPlanner(llm=llm, use_llm=True)
        strategy = planner.plan("分析 Cursor，官网是 https://custom.example.com")
        assert strategy.competitor.official_links.get("home") == "https://custom.example.com"
