"""设计文档 70 M1 — 呈现层自由化单测（对比/普查路径）。

覆盖：
① Lead 正文 + 代码矩阵附录（正文在前、矩阵在后，信息不丢）；
② mock 纯 JSON → 正文空 → 保留矩阵 + ## 市场格局核心结论 段（确定性不变）；
③ `_lead_body_text`：去 Final Answer 前缀、剔除对比 JSON 块；
④ 开关（use_lead_body 显式 / config 默认）。
"""
from __future__ import annotations

import json

from competitor_agent.config.loader import AppConfig
from competitor_agent.facade.comparison_report import _lead_body_text, assemble_comparison

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


class TestLeadBodyText:
    def test_strips_json_and_prefix(self):
        text = _lead_body_text('Final Answer: 以下是对比结论。\n\n{"competitors": ["a"], "kind": "compare"}')
        assert "Final Answer:" not in text
        assert '"competitors"' not in text
        assert "以下是对比结论" in text

    def test_pure_json_returns_empty(self):
        assert _lead_body_text('{"competitors": ["a"], "kind": "compare", "conclusion": "A 领先"}') == ""

    def test_prose_only_kept(self):
        assert _lead_body_text("Cursor 整体领先。") == "Cursor 整体领先。"


class TestAssembleComparison:
    def test_lead_body_plus_matrix(self):
        lead_answer = "## 格局结论\n\nCursor 定价更贵但功能更全。\n\n" + json.dumps(
            {"competitors": ["cursor", "windsurf"], "kind": "compare"}, ensure_ascii=False
        )
        comparison = assemble_comparison(lead_answer, _PLAN, _CANDS, use_lead_body=True)
        md = comparison.markdown_report
        assert md.startswith("## 格局结论")
        assert "Cursor 定价更贵但功能更全" in md
        assert "品类格局矩阵" in md  # 代码矩阵附录在后
        assert md.index("Cursor 定价更贵但功能更全") < md.index("品类格局矩阵")

    def test_pure_json_falls_back_to_matrix_and_conclusion(self):
        lead_answer = json.dumps(
            {"competitors": ["cursor", "windsurf"], "kind": "compare",
             "conclusion": "Cursor 综合领先"}, ensure_ascii=False
        )
        comparison = assemble_comparison(lead_answer, _PLAN, _CANDS, use_lead_body=True)
        md = comparison.markdown_report
        assert "品类格局矩阵" in md
        assert "## 市场格局核心结论" in md
        assert "Cursor 综合领先" in md

    def test_use_lead_body_false_keeps_conclusion_section(self):
        # 关闭正文优先：只保留矩阵 + ## 市场格局核心结论 段（marker 提取）
        lead_answer = "## 格局结论\n\nCursor 更强。\n\n【市场格局核心结论】Cursor 是最佳选择"
        comparison = assemble_comparison(lead_answer, _PLAN, _CANDS, use_lead_body=False)
        md = comparison.markdown_report
        assert "品类格局矩阵" in md
        assert "## 市场格局核心结论" in md
        assert "Cursor 是最佳选择" in md

    def test_config_default_true(self, monkeypatch):
        cfg = AppConfig()
        cfg.report.lead_formatted_body = True
        monkeypatch.setattr("competitor_agent.config.loader.load_config", lambda: cfg)
        lead_answer = "## 结论\n\n正文正文。\n\n" + json.dumps({"kind": "compare"}, ensure_ascii=False)
        comparison = assemble_comparison(lead_answer, _PLAN, _CANDS)
        assert comparison.markdown_report.startswith("## 结论")

    def test_config_default_false(self, monkeypatch):
        cfg = AppConfig()
        cfg.report.lead_formatted_body = False
        monkeypatch.setattr("competitor_agent.config.loader.load_config", lambda: cfg)
        lead_answer = "## 结论\n\n正文正文。\n\n【市场格局核心结论】Cursor 最佳"
        comparison = assemble_comparison(lead_answer, _PLAN, _CANDS)
        assert "品类格局矩阵" in comparison.markdown_report
        assert "## 市场格局核心结论" in comparison.markdown_report
        assert "Cursor 最佳" in comparison.markdown_report


class TestZeroCandidateRobustness:
    """设计文档 70 §8.1 D1d：零候选对比报告健壮性——空报告仍落盘 .md（提示留痕）。"""

    def test_zero_candidate_empty_lead_answer_gets_hint(self):
        comparison = assemble_comparison("", _PLAN, {}, use_lead_body=True)
        assert comparison.reports == []
        assert comparison.markdown_report.strip()
        assert "未收集到候选数据" in comparison.markdown_report

    def test_zero_candidate_with_lead_body_appends_hint(self):
        lead_answer = "## 格局结论\n\n候选采集失败，以下是已获取信息。\n"
        comparison = assemble_comparison(lead_answer, _PLAN, {}, use_lead_body=True)
        assert lead_answer.strip() in comparison.markdown_report
        assert "未收集到候选数据" in comparison.markdown_report

    def test_zero_candidate_keep_conclusion_plus_hint(self):
        lead_answer = "## 结论\n\n综合判断无可靠候选。\n\n【市场格局核心结论】暂无可靠候选"
        comparison = assemble_comparison(lead_answer, _PLAN, {}, use_lead_body=False)
        assert comparison.markdown_report.strip()
        assert "未收集到候选数据" in comparison.markdown_report
        assert "暂无可靠候选" in comparison.markdown_report
