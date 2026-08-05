"""core/task_parser.py + competitor_registry 对比拆分 单测（M5.4）"""
from competitor_agent.core.competitor_registry import resolve_competitors, split_compare_text
from competitor_agent.core.task_parser import DIMENSION_KEYWORDS, parse_task
from competitor_agent.llm.client import LLMClient


class TestSplitCompare:
    def test_compare_with_he(self):
        assert split_compare_text("对比 Cursor 和 Windsurf") == ["Cursor", "Windsurf"]

    def test_compare_with_vs(self):
        assert split_compare_text("Cursor vs Windsurf") == ["Cursor", "Windsurf"]

    def test_compare_with_yu(self):
        parts = split_compare_text("比较 Cursor 与 Windsurf")
        assert parts == ["Cursor", "Windsurf"]

    def test_not_compare(self):
        assert split_compare_text("分析 Cursor 的定价") is None

    def test_resolve_competitors_compare(self):
        competitors = resolve_competitors("对比 Cursor 和 Windsurf")
        assert len(competitors) == 2
        assert competitors[0].name == "cursor"
        assert competitors[1].name == "windsurf"

    def test_resolve_competitors_single(self):
        competitors = resolve_competitors("分析 Claude Code")
        assert len(competitors) == 1
        assert competitors[0].name == "claude-code"


class TestParseTask:
    def test_single_competitor(self):
        result = parse_task("分析 Cursor")
        assert result.competitors == ["cursor"]
        assert not result.is_compare

    def test_compare_task(self):
        result = parse_task("对比 Cursor 和 Windsurf")
        assert result.competitors == ["cursor", "windsurf"]
        assert result.is_compare

    def test_dimension_only_pricing(self):
        result = parse_task("只分析 Cursor 定价")
        assert result.dimensions == ["pricing"]

    def test_dimension_unknown_returns_none(self):
        result = parse_task("分析 Cursor")
        assert result.dimensions is None

    def test_dimension_keywords_defined(self):
        assert "pricing" in DIMENSION_KEYWORDS
        assert "performance" in DIMENSION_KEYWORDS

    def test_custom_source_home(self):
        result = parse_task("分析 Cursor，官网是 https://cursor.com")
        assert result.custom_sources.get("home") == "https://cursor.com"

    def test_custom_source_pricing_page(self):
        result = parse_task("分析 Cursor，定价页 https://cursor.com/pricing")
        assert result.custom_sources.get("pricing") == "https://cursor.com/pricing"


class TestParseTaskLLM:
    def test_llm_parses_and_falls_back_on_garbage(self):
        llm = LLMClient(call_func=lambda messages, model: '{"competitors": ["cursor"], "dimensions": ["pricing"], "custom_sources": {}}')
        result = parse_task("分析 Cursor", llm=llm, use_llm=True)
        assert result.competitors == ["cursor"]
        assert result.dimensions == ["pricing"]

    def test_llm_garbage_falls_back_to_rules(self):
        llm = LLMClient(call_func=lambda messages, model: "不是 JSON")
        result = parse_task("只分析 Cursor 定价", llm=llm, use_llm=True)
        assert result.dimensions == ["pricing"]

    def test_no_llm_uses_rules(self):
        result = parse_task("对比 Cursor 和 Windsurf", llm=None, use_llm=False)
        assert result.is_compare


class TestStrategicLoopDimensions:
    def test_dimension_whitelist_restricts_gaps(self):
        from competitor_agent.core.strategic_loop import StrategicPlanner

        planner = StrategicPlanner()
        strategy = planner.plan("只分析 Cursor 定价")
        assert [g.field for g in strategy.gaps] == ["pricing"]

    def test_custom_source_merged_into_links(self):
        from competitor_agent.core.strategic_loop import StrategicPlanner

        planner = StrategicPlanner()
        strategy = planner.plan("分析 Cursor，官网是 https://custom.example.com")
        assert strategy.competitor.official_links.get("home") == "https://custom.example.com"
