"""设计文档 95 — 对比/普查路径结论段 writer 化（JSON 泄漏根治）。

覆盖：
① 矩阵组装（plan 排序 / 零候选提示留痕，代码确定性）；
② Lead Final Answer 全形态（dict conclusion / 烂 JSON / 散文）→ 报告正文零 JSON 泄漏
   （原 ``_extract_conclusion`` 解析兜底入口整体删除，回归核心用例）；
③ writer 通道：``run_comparison_writer_pass`` prose_override 直注 → 「## 市场格局核心结论」
   段为注入 prose；writer 关闭/异常/零候选 → 无结论段、矩阵完好。
"""
from __future__ import annotations

import pytest
from competitor_agent.config.loader import ReportConfig
from competitor_agent.facade import writer_pass
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

_CFG = ReportConfig(writer_pass=True, writer_slot_max_retries=1)


class TestMatrixAssembly:
    def test_matrix_renders_and_no_conclusion_section(self):
        """组装层只产矩阵：无 writer 接线则无结论段（设计文档 95 §3.1）。"""
        comparison = assemble_comparison(_PLAN, _CANDS)
        md = comparison.markdown_report
        assert "品类格局矩阵" in md
        assert [r.competitor.name for r in comparison.reports] == ["cursor", "windsurf"]
        assert "## 市场格局核心结论" not in md

    def test_zero_candidate_empty_answer_gets_hint(self):
        comparison = assemble_comparison(_PLAN, {})
        assert comparison.reports == []
        assert comparison.markdown_report.strip()
        assert "未收集到候选数据" in comparison.markdown_report

    def test_zero_candidate_hint_exactly_once(self):
        """结论兜底退役后：零候选提示恰好 1 处（原布尔守卫双追加语义随之退役）。"""
        comparison = assemble_comparison(_PLAN, {})
        assert comparison.markdown_report.count("未收集到候选数据") == 1


class TestNoJsonLeak:
    """回归核心用例（doc95 §1/§2）：Lead Final Answer 全形态 → 报告正文零 JSON 泄漏。"""

    def test_conclusion_dict_no_leak(self):
        """路径 B 回归：conclusion 为嵌套 dict（原 str(dict) 泄漏 Python repr）。"""
        # Lead 已不入组装签名：dict/烂 JSON/散文任何形态都无入口
        comparison = assemble_comparison(_PLAN, _CANDS)
        assert "{" not in comparison.markdown_report
        assert "'" not in comparison.markdown_report
        assert "## 市场格局核心结论" not in comparison.markdown_report

    def test_malformed_lead_answer_no_entry(self):
        """路径 A 回归：烂 JSON/散文不再被整段兜底为结论（垃圾无入口）。"""
        comparison = assemble_comparison(_PLAN, _CANDS)
        assert "Final Answer" not in comparison.markdown_report
        assert "品类格局矩阵" in comparison.markdown_report


class TestComparisonWriterChannel:
    def test_prose_override_appends_section(self):
        """prose_override 直注 → 结论段为注入 prose（复用注入与锚定链路）。"""
        comparison = assemble_comparison(_PLAN, _CANDS)
        writer_pass.run_comparison_writer_pass(
            comparison, llm=None, config=_CFG, prose_override="Cursor 综合领先。"
        )
        md = comparison.markdown_report
        assert "## 市场格局核心结论" in md
        assert "Cursor 综合领先。" in md
        assert "品类格局矩阵" in md  # 矩阵完好

    def test_prose_override_idempotent(self):
        comparison = assemble_comparison(_PLAN, _CANDS)
        writer_pass.run_comparison_writer_pass(
            comparison, llm=None, config=_CFG, prose_override="Cursor 综合领先。"
        )
        writer_pass.run_comparison_writer_pass(
            comparison, llm=None, config=_CFG, prose_override="重复注入不应发生。"
        )
        assert comparison.markdown_report.count("## 市场格局核心结论") == 1
        assert "重复注入不应发生" not in comparison.markdown_report

    def test_writer_off_no_section(self):
        """writer 关闭（llm=None 模拟不写作）→ 无结论段，矩阵完好。"""
        comparison = assemble_comparison(_PLAN, _CANDS)
        writer_pass.run_comparison_writer_pass(comparison, llm=None, config=_CFG)
        assert "## 市场格局核心结论" not in comparison.markdown_report
        assert "品类格局矩阵" in comparison.markdown_report

    def test_zero_candidates_writer_noop(self):
        """零候选 → 无事实 → 槽位跳过（与结论段正交，提示留痕不变）。"""
        comparison = assemble_comparison(_PLAN, {})
        writer_pass.run_comparison_writer_pass(
            comparison, llm=None, config=_CFG, prose_override="不应出现"
        )
        assert "## 市场格局核心结论" not in comparison.markdown_report
        assert "未收集到候选数据" in comparison.markdown_report


class TestOverallDegradationGuard:
    def test_maybe_swallows_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """降级形态一：writer 整体异常 → markdown 保持矩阵产物不动。"""
        comparison = assemble_comparison(_PLAN, _CANDS)
        before = comparison.markdown_report

        def _boom(*a: object, **kw: object) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(writer_pass, "run_comparison_writer_pass", _boom)
        writer_pass.maybe_run_comparison_writer_pass(comparison, llm=None, config=_CFG)
        assert comparison.markdown_report == before
