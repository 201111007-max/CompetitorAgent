"""设计文档 88 §7 第 7 步 — Lead Final Answer 两段式退役（单竞品路径）。

覆盖：
① `assemble`：REPORT_SCHEMA JSON 是唯一事实源——Lead 散文正文不再消费，
   markdown 恒由代码模板渲染（`lead_formatted_body` 开关随两段式退役删除）；
② 纯散文（无 JSON）→ `_fallback_single_dimension` 兜底（react 维度）；
③ 模板保底锚点（"# cursor 竞品分析报告" 渲染不变，既有模板断言零回归）。
"""
from __future__ import annotations

import json

from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.facade.react_report import assemble

_DIM = {
    "dimension": "pricing",
    "summary": "Pro $20/mo",
    "details": {"plans": ["Pro"]},
    "confidence": 0.8,
    "evidence_urls": ["https://cursor.com/pricing"],
}
_JSON = json.dumps({"competitor": "cursor", "dimensions": [_DIM]}, ensure_ascii=False)


class TestAssembleJsonOnlySource:
    def test_prose_plus_json_json_wins(self):
        """散文正文被忽略：JSON 是唯一事实源，markdown 由模板渲染。"""
        answer = f"## 执行摘要\n\nCursor 在定价上最激进。\n\n{_JSON}"
        report = assemble(answer, Competitor(name="cursor"), loop_plan=None)
        assert "# cursor 竞品分析报告" in report.markdown_report
        assert "## 维度结论" in report.markdown_report
        assert "Cursor 在定价上最激进" not in report.markdown_report
        assert report.dimension_results[0].dimension == "pricing"

    def test_pure_json_renders_template(self):
        report = assemble(_JSON, Competitor(name="cursor"), loop_plan=None)
        assert report.markdown_report.startswith("# cursor 竞品分析报告")
        assert "## 维度结论" in report.markdown_report

    def test_prose_only_falls_back_to_react_dimension(self):
        report = assemble("只有散文，没有结构化结论。", Competitor(name="cursor"), loop_plan=None)
        assert report.dimension_results[0].dimension == "react"

    def test_prose_braces_survive_in_fallback_summary(self):
        """散文花括号不是 JSON dump → 兜底 summary 保留（不误删）。"""
        report = assemble(
            "结果（花括号 {请忽略} 是散文）", Competitor(name="cursor"), loop_plan=None
        )
        assert "{请忽略}" in report.dimension_results[0].summary

    def test_template_anchors(self):
        """模板保底锚点（既有 44 处模板断言不变的回归锚点）。"""
        report = assemble(_JSON, Competitor(name="cursor"), loop_plan=None)
        assert report.markdown_report.startswith("# cursor 竞品分析报告")
        assert "## 维度结论" in report.markdown_report
        assert "### [OK] pricing" in report.markdown_report
        assert "证据:" in report.markdown_report
