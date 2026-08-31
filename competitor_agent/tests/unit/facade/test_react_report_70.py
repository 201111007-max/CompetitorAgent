"""设计文档 70 M1 — 呈现层自由化单测（单竞品路径）。

覆盖：
① `_split_body_and_payload`：纯 JSON / 正文+JSON / 纯散文 / 散文花括号不误删；
② `assemble` 正文优先/模板保底/开关（use_lead_body 显式 + config 默认）；
③ mock 纯 JSON → body 空 → 模板保底（既有 44 处模板断言不变的回归锚点）。
"""
from __future__ import annotations

import json

from competitor_agent.config.loader import AppConfig
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.facade.react_report import (
    _split_body_and_payload,
    assemble,
)

_DIM = {
    "dimension": "pricing",
    "summary": "Pro $20/mo",
    "details": {"plans": ["Pro"]},
    "confidence": 0.8,
    "evidence_urls": ["https://cursor.com/pricing"],
}
_JSON = json.dumps({"competitor": "cursor", "dimensions": [_DIM]}, ensure_ascii=False)


class TestSplitBodyAndPayload:
    def test_pure_json_body_empty(self):
        body, payload = _split_body_and_payload(_JSON)
        assert body == ""
        assert payload is not None
        assert payload["competitor"] == "cursor"

    def test_prose_plus_json_body_is_prose(self):
        answer = f"## 结论先行\n\nCursor 定价激进。\n\n{_JSON}"
        body, payload = _split_body_and_payload(answer)
        assert payload is not None
        assert "Cursor 定价激进" in body
        assert '"competitor"' not in body
        assert body.startswith("## 结论先行")

    def test_prose_only_payload_none(self):
        body, payload = _split_body_and_payload("只有散文，没有结构化结论。")
        assert body == "只有散文，没有结构化结论。"
        assert payload is None

    def test_prose_braces_not_stripped(self):
        answer = "结果（花括号 {请忽略} 是散文）"
        body, _ = _split_body_and_payload(answer)
        assert "{请忽略}" in body

    def test_structured_data_section_stripped(self):
        answer = (
            "## 结论\n\n正文。\n\n## 七、结构化数据（JSON）\n```json\n\n补充披露：部分源不可用。\n```\n\n"
            + _JSON
        )
        body, payload = _split_body_and_payload(answer)
        assert "结构化数据" not in body
        assert "补充披露" not in body
        assert "正文" in body
        assert payload is not None


class TestAssembleUseLeadBody:
    def test_lead_body_wins_when_prose(self):
        prose = "## 执行摘要\n\nCursor 在定价上最激进。"
        answer = f"{prose}\n\n{_JSON}"
        report = assemble(answer, Competitor(name="cursor"), loop_plan=None, use_lead_body=True)
        assert report.markdown_report == prose
        assert report.dimension_results[0].dimension == "pricing"

    def test_lead_body_off_falls_back_to_template(self):
        answer = f"## 执行摘要\n\nCursor 在定价上最激进。\n\n{_JSON}"
        report = assemble(answer, Competitor(name="cursor"), loop_plan=None, use_lead_body=False)
        assert "# cursor 竞品分析报告" in report.markdown_report
        assert "## 维度结论" in report.markdown_report
        assert report.markdown_report != "## 执行摘要\n\nCursor 在定价上最激进。"

    def test_pure_json_falls_back_to_template(self):
        report = assemble(_JSON, Competitor(name="cursor"), loop_plan=None, use_lead_body=True)
        assert "# cursor 竞品分析报告" in report.markdown_report
        assert "## 维度结论" in report.markdown_report

    def test_config_default_true(self, monkeypatch):
        cfg = AppConfig()
        cfg.report.lead_formatted_body = True
        monkeypatch.setattr("competitor_agent.config.loader.load_config", lambda: cfg)
        prose = "## 用户要的报告"
        report = assemble(f"{prose}\n\n{_JSON}", Competitor(name="cursor"), loop_plan=None)
        assert report.markdown_report == prose

    def test_config_default_false(self, monkeypatch):
        cfg = AppConfig()
        cfg.report.lead_formatted_body = False
        monkeypatch.setattr("competitor_agent.config.loader.load_config", lambda: cfg)
        report = assemble(f"## 用户要的报告\n\n{_JSON}", Competitor(name="cursor"), loop_plan=None)
        assert "# cursor 竞品分析报告" in report.markdown_report

    def test_leader_template_anchors_when_body_empty(self):
        """mock 纯 JSON → 模板保底（正文为空时既有模板断言不变的锚点）。"""
        report = assemble(_JSON, Competitor(name="cursor"), loop_plan=None, use_lead_body=True)
        assert report.markdown_report.startswith("# cursor 竞品分析报告")
        assert "## 维度结论" in report.markdown_report
        assert "### [OK] pricing" in report.markdown_report
        assert "证据:" in report.markdown_report
