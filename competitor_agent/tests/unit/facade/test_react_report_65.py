"""设计文档 65 §2 — 报告 JSON 提取健壮化单测。

覆盖：
① `_extract_json_block` 括号配平 + 字符串字面量感知（"散文前缀 + JSON"、纯 JSON、
   纯散文、损坏 JSON、JSON 字符串内含花括号、尾部散文）；
② `_parse_report` 四类输入：散文前缀+JSON → 多维度 / 纯 JSON → 多维度 /
   纯散文 → None / 损坏 JSON → None；缺 dimensions 的 dict → 可溯源单 react 维度；
③ `_fallback_single_dimension` 兜底净化：解析失败时 react 维度 summary 不含 JSON 块；
④ `comparison_report._extract_conclusion` 复用提取器（散文前缀 + conclusion）；
⑤ `_plan_resolution` 多候选推断（candidate_count > 0 → discovery/compare）。
"""
from __future__ import annotations

import json

from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.facade.comparison_report import _extract_conclusion
from competitor_agent.facade.react_report import (
    _extract_json_block,
    _fallback_single_dimension,
    _parse_report,
    _strip_json_blocks,
    assemble,
)

_DIM = {
    "dimension": "market",
    "summary": "市场份额 45%",
    "details": {"share": 0.45},
    "confidence": 0.8,
    "evidence_urls": ["http://x.com"],
}
_JSON = json.dumps({"competitor": "A", "dimensions": [_DIM]}, ensure_ascii=False)


class TestExtractJsonBlock:
    def test_pure_json(self):
        assert _extract_json_block('{"a": 1}') == {"a": 1}

    def test_prose_prefix_json(self):
        block = _extract_json_block(f"数据已齐备。以下是最终竞品分析报告。\n\n{_JSON!s}")
        assert block is not None and block["competitor"] == "A"

    def test_json_with_trailing_prose(self):
        block = _extract_json_block('{"a": 1} 尾部散文说明')
        assert block == {"a": 1}

    def test_prose_only_returns_none(self):
        assert _extract_json_block("这是纯散文，没有 JSON。{} 之类。") is None

    def test_broken_json_returns_none(self):
        assert _extract_json_block('{"competitor": "A", broken') is None

    def test_string_literal_braces_not_confused(self):
        tricky = '先导文本 {"dimensions":[{"dimension":"m","summary":"a {b} c","details":{},"confidence":0.5}]} 尾部'
        block = _extract_json_block(tricky)
        assert block is not None
        assert block["dimensions"][0]["summary"] == "a {b} c"

    def test_empty_dict_placeholder_ignored(self):
        assert _extract_json_block("结果: {} 请参考") is None


class TestParseReport:
    def test_prose_prefix_parses_to_dimensions(self):
        payload = _parse_report(f"数据已齐备。以下是最终竞品分析报告。\n\n{_JSON!s}")
        assert payload is not None
        assert payload["dimensions"][0]["dimension"] == "market"

    def test_pure_json_parses(self):
        payload = _parse_report('{"competitor":"A","dimensions":[{"dimension":"m","summary":"s","details":{},"confidence":0.9}]}')
        assert payload is not None

    def test_prose_only_none(self):
        assert _parse_report("这是纯散文，没有结构化结论。") is None

    def test_broken_json_none(self):
        assert _parse_report('{"competitor": "A", broken') is None

    def test_dict_without_dimensions_falls_back_to_field(self):
        payload = _parse_report('{"conclusion": "核心结论：A 领先"}')
        assert payload is not None
        assert payload["dimensions"][0]["dimension"] == "react"
        assert payload["dimensions"][0]["summary"] == "核心结论：A 领先"

    def test_empty_text_none(self):
        assert _parse_report("") is None
        assert _parse_report(None) is None  # type: ignore[arg-type]


class TestFallbackSanitize:
    def test_fallback_removes_json_dump(self):
        answer = 'Lead 分析完成。\n\n{"dimensions":[{"dimension":"react","summary":"x","details":{},"confidence":0.4}]} 无结论。'
        text = _strip_json_blocks(answer)
        assert '"dimensions"' not in text
        assert "Lead 分析完成" in text

    def test_fallback_single_dimension_summary_has_no_json(self):
        """设计文档 65 §5.2：解析失败时 react 维度 summary 不含 {…} JSON 块。"""
        from competitor_agent.core.report_builder import ReportBuilder

        answer = '以下是报告。\n\n{"competitor":"A","dimensions":[{"dimension":"x","summary":"y"}]} 但这不是有效结论'
        report = _fallback_single_dimension(
            answer, Competitor(name="A"), ReportBuilder(), "partial"
        )
        dr = report.dimension_results[0]
        assert dr.dimension == "react"
        assert '"dimensions"' not in dr.summary
        assert "但是" in dr.summary or "但这不是" in dr.summary

    def test_assemble_prose_prefix_multidim(self):
        report = assemble(f"数据已齐备。\n\n{_JSON!s}", Competitor(name="A"), loop_plan=None)
        assert [d.dimension for d in report.dimension_results] == ["market"]
        assert report.terminal_state == "success"

    def test_assemble_broken_json_no_crash(self):
        report = assemble('{"competitor": "A", broken', Competitor(name="A"), loop_plan=None)
        assert report.dimension_results[0].dimension == "react"


class TestComparisonConclusion:
    def test_prose_prefix_conclusion(self):
        assert _extract_conclusion('Final Answer: 数据已齐备。\n\n{"conclusion":"市场格局核心结论：A 领先"}') == "市场格局核心结论：A 领先"

    def test_pure_json_conclusion(self):
        assert _extract_conclusion('{"conclusion":"B 领先"}') == "B 领先"

    def test_marker_wins(self):
        assert _extract_conclusion("前言【市场格局核心结论】A 最强") == "A 最强"

    def test_prose_no_conclusion(self):
        assert _extract_conclusion("没有结构化结论的散文。") == "没有结构化结论的散文。"


class TestMalformedJsonLightFix:
    """设计文档 66 §3.3 — 模型手滑畸形 JSON 轻修复 + "像报告 JSON 就剔除"判定。"""

    def test_empty_value_fixed_to_null(self):
        block = '{"competitor": "A", "dimensions": [{"dimension": "m", "details": , "confidence": 0.8}]}'
        payload = _extract_json_block(block)
        assert payload is not None
        assert payload["dimensions"][0]["details"] is None

    def test_empty_array_items_fixed(self):
        block = '{"competitor": "A", "dimensions": [ , , , ]}'
        payload = _extract_json_block(block)
        assert payload is not None
        assert payload["dimensions"] == []

    def test_prose_prefix_malformed_fixed(self):
        block = '以下是报告。\n\n{"competitor": "A", "dimensions": [{"dimension": "m", "details": , }]}'
        payload = _extract_json_block(block)
        assert payload is not None
        assert payload["competitor"] == "A"

    def test_parse_report_recovers_malformed(self):
        block = '{"competitor": "A", "dimensions": [{"dimension": "m", "summary": "s", "details": , "confidence": 0.9}]}'
        payload = _parse_report(block)
        assert payload is not None
        assert payload["dimensions"][0]["dimension"] == "m"

    def test_strip_removes_malformed_report_block(self):
        text = 'Lead 输出。\n\n{"competitor": "A", "dimensions": [, , ,]} 结束。'
        cleaned = _strip_json_blocks(text)
        assert '"competitor"' not in cleaned
        assert "Lead 输出" in cleaned

    def test_strip_preserves_prose_braces(self):
        text = "结果（含花括号 {请忽略} 的散文）"
        cleaned = _strip_json_blocks(text)
        assert "{请忽略}" in cleaned


class TestPlanResolution:
    def test_multi_candidate_inferred_discovery(self):
        from competitor_agent.core.task_parser import ResolutionDecision
        from competitor_agent.facade.api import CompetitorAnalysisAPI

        class P:
            resolution = ResolutionDecision.DISCOVERY

        class C:
            resolution = ResolutionDecision.COMPARE

        class R:
            resolution = ResolutionDecision.REGISTRY

        # plan 缺 resolution/competitors，但 candidate_count>0 → discovery
        assert CompetitorAnalysisAPI._plan_resolution({"competitor": "A"}, P(), candidate_count=3) == "discovery"
        # 设计文档 66 §3.2：parse_task（LLM）判 COMPARE/DISCOVERY 且 plan 缺字段
        # （零候选）→ 尊重主 Agent 意图 → 走 comparison 组装（不落 registry 单报告路径）
        assert CompetitorAnalysisAPI._plan_resolution({"competitor": "A"}, P()) == "discovery"
        assert CompetitorAnalysisAPI._plan_resolution({"competitor": "A"}, C()) == "compare"
        # registry + 单值仍归 registry（回归）
        assert CompetitorAnalysisAPI._plan_resolution({"competitor": "A"}, R()) == "registry"
        # plan.competitors 存在 + COMPARE → compare
        assert CompetitorAnalysisAPI._plan_resolution({"competitors": ["A", "B"]}, C()) == "compare"
        # plan.resolution 优先
        assert CompetitorAnalysisAPI._plan_resolution({"resolution": "registry"}, P(), candidate_count=3) == "registry"
