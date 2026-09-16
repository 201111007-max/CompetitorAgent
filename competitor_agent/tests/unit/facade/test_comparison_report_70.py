"""设计文档 88 §7 第 7 步 — 对比/普查路径两段式退役（单一事实源）。

覆盖：
① comparison JSON ``conclusion`` 字段 → 「## 市场格局核心结论」段
   （【市场格局核心结论】marker 字符串契约删除，结论统一走结构化字段）；
② 矩阵 + 结论段渲染（代码确定性）；
③ 零候选健壮性（提示留痕）。
"""
from __future__ import annotations

import json

from competitor_agent.facade.comparison_report import assemble_comparison

_PLAN = {"resolution": "compare", "competitors": ["cursor", "windsurf"]}
_CANDS = {
    "cursor": {
        "competitor": "cursor",
        "dimensions": [
            {"dimension": "pricing", "summary": "Pro $20", "details": {"plans": ["Pro"]},
             "confidence": 0.8, "evidence_urls": ["https://cursor.com/pricing"]},
        ],
    },
    "windsurf": {
        "competitor": "windsurf",
        "dimensions": [
            {"dimension": "pricing", "summary": "$15", "details": {"plans": ["Free"]},
             "confidence": 0.7, "evidence_urls": ["https://windsurf.com/pricing"]},
        ],
    },
}


class TestConclusionFromJsonField:
    def test_json_conclusion_renders_section(self):
        lead_answer = json.dumps(
            {"competitors": ["cursor", "windsurf"], "kind": "compare",
             "conclusion": "Cursor 综合领先"}, ensure_ascii=False
        )
        comparison = assemble_comparison(lead_answer, _PLAN, _CANDS)
        md = comparison.markdown_report
        assert "品类格局矩阵" in md
        assert "## 市场格局核心结论" in md
        assert "Cursor 综合领先" in md

    def test_prose_prefix_json_conclusion(self):
        """散文前缀 + JSON：括号配平提取 conclusion 字段（doc 65 §2.3 契约不变）。"""
        lead_answer = (
            'Final Answer: 数据已齐备。\n\n{"competitors": ["cursor", "windsurf"], '
            '"conclusion": "Cursor 综合领先"}'
        )
        comparison = assemble_comparison(lead_answer, _PLAN, _CANDS)
        md = comparison.markdown_report
        assert "## 市场格局核心结论" in md
        assert "Cursor 综合领先" in md

    def test_json_without_conclusion_no_section(self):
        lead_answer = json.dumps(
            {"competitors": ["cursor"], "kind": "compare"}, ensure_ascii=False
        )
        comparison = assemble_comparison(lead_answer, _PLAN, _CANDS)
        assert "品类格局矩阵" in comparison.markdown_report
        assert "## 市场格局核心结论" not in comparison.markdown_report

    def test_no_json_whole_text_fallback(self):
        """非 JSON（真实 LLM 未遵约）→ 整段兜底为结论，信息不丢。"""
        comparison = assemble_comparison("Cursor 整体领先", _PLAN, _CANDS)
        assert "## 市场格局核心结论" in comparison.markdown_report
        assert "Cursor 整体领先" in comparison.markdown_report


class TestZeroCandidateRobustness:
    """设计文档 70 §8.1 D1d：零候选对比报告健壮性——空报告仍落盘 .md（提示留痕）。"""

    def test_zero_candidate_empty_lead_answer_gets_hint(self):
        comparison = assemble_comparison("", _PLAN, {})
        assert comparison.reports == []
        assert comparison.markdown_report.strip()
        assert "未收集到候选数据" in comparison.markdown_report

    def test_zero_candidate_conclusion_plus_hint(self):
        """JSON conclusion + 零候选：结论段与提示共存（布尔守卫语义）。"""
        lead_answer = json.dumps({"conclusion": "暂无可靠候选"}, ensure_ascii=False)
        comparison = assemble_comparison(lead_answer, _PLAN, {})
        assert comparison.markdown_report.strip()
        assert "未收集到候选数据" in comparison.markdown_report
        assert "暂无可靠候选" in comparison.markdown_report
