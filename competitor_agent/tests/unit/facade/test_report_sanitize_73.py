"""设计文档 73 §3.1-3.3 — 报告正文防御性净化单测。

- H1 归并去重（草稿+正式稿 → 只留正式稿；单 H1 逐字节不变）；
- 未闭合围栏兜底（``` 失衡 → 补闭合；配平原样）；
- 追加守卫布尔化（模型把提示抄进正文 → 代码仍按布尔标志追加，提示不丢）。

设计文档 88 步骤 7（两段式退役）：净化链收敛进 `_fallback_single_dimension`
（`_strip_structured_data_section` 随 Lead 散文正文概念退役删除）。
"""

from __future__ import annotations

from competitor_agent.facade.comparison_report import (
    _ZERO_CANDIDATE_HINT,
    assemble_comparison,
)
from competitor_agent.facade.react_report import (
    _close_orphan_fence,
    _dedupe_repeated_report,
    _strip_json_blocks,
)


def test_dedupe_keeps_last_h1() -> None:
    text = (
        "# Coding Agent 市场分析报告\n\n草稿内容（应被丢弃）\n\n"
        "# Coding Agent 市场分析报告\n\n正式稿内容（保留）\n"
    )
    out = _dedupe_repeated_report(text)
    assert out.count("# Coding Agent 市场分析报告") == 1
    assert "正式稿内容" in out
    assert "草稿内容" not in out


def test_dedupe_single_h1_unchanged() -> None:
    text = "# 单一报告\n\n只有一份正文\n"
    assert _dedupe_repeated_report(text) == text


def test_dedupe_no_h1_unchanged() -> None:
    text = "没有一级标题的正文\n"
    assert _dedupe_repeated_report(text) == text


def test_dedupe_ignores_h1_inside_fence() -> None:
    """复查修复：``` 围栏内的 ``# `` 注释行不当作第二个 H1（否则标题与前半正文被误删）。"""
    text = (
        "# 市场分析报告\n\n正文开头\n\n"
        "```bash\n# 围栏注释（不是标题）\ncmd --flag\n```\n\n结尾\n"
    )
    out = _dedupe_repeated_report(text)
    assert "# 市场分析报告" in out
    assert "正文开头" in out
    assert "结尾" in out
    assert out == text  # 单真实 H1 → 逐字节不变


def test_fence_closes_orphan() -> None:
    text = "正文\n```json\n{\"a\": 1}\n"
    out = _close_orphan_fence(text)
    assert out.count("```") % 2 == 0
    assert out.endswith("```\n")


def test_fence_balanced_unchanged() -> None:
    text = "正文\n```\n代码\n```\n结尾\n"
    assert _close_orphan_fence(text) == text


def test_fallback_chain_dedupes_and_closes_fence() -> None:
    """组合：草稿+正式稿 + 截断围栏 → 兜底净化后只留正式稿、无未闭合围栏。

    设计文档 88 步骤 7：两段式退役后净化链唯一存活消费方 = `_fallback_single_dimension`
    （`_strip_structured_data_section` 已删除，不再断言"结构化数据"段剥离）。
    """
    draft = "# Coding Agent 市场分析报告\n\n草稿正文（丢）\n\n## 市场格局核心结论\n\n草稿结论（丢）\n\n"
    formal = "# Coding Agent 市场分析报告\n\n## 一、结论先行\n\n正式结论\n\n```json\n{\"x\": 1}\n"
    text = _close_orphan_fence(_dedupe_repeated_report(_strip_json_blocks(draft + formal)))
    assert text.count("# Coding Agent 市场分析报告") == 1
    assert "草稿正文" not in text
    assert "正式结论" in text
    assert text.count("```") % 2 == 0, "无未闭合围栏"


def test_guard_boolean_appends_despite_copied_hint() -> None:
    """§3.3：模型把提示文本抄进正文中间 → 代码仍按布尔标志追加（提示不丢）。

    旧实现按「字符串存在性」判断 → 模型抄写后代码跳过追加（提示只有 1 处）；
    新实现按布尔标志 → 追加生效（提示留痕 1 处 + 结论兜底段携带 1 处 = 2）。
    """
    lead_answer = (
        "# 对比报告\n\n未收集到候选数据，对比矩阵为空。\n\n一些正文内容\n\n"
        "【市场格局核心结论】\n整体格局稳定。\n"
    )
    report = assemble_comparison(
        lead_answer=lead_answer,
        plan=None,
        candidate_results={},
    )
    assert report.competitors == []
    assert report.markdown_report.count(_ZERO_CANDIDATE_HINT) == 2


def test_guard_boolean_no_duplicate_when_no_copied() -> None:
    """正常零候选：正文无提示 → 代码追加恰好 1 处。"""
    lead_answer = "# 对比报告\n\n只有正文，没有抄写提示。\n"
    report = assemble_comparison(
        lead_answer=lead_answer,
        plan=None,
        candidate_results={},
    )
    assert report.markdown_report.count(_ZERO_CANDIDATE_HINT) == 1


def test_export_skips_empty_shell_for_survey() -> None:
    """设计文档 73 §3.4 + D1 方案 A：普查/零候选不落空壳矩阵 compare.json。

    enable_rag=False：导出逻辑与知识库无关，不得触碰真实用户数据目录
    （真实 KB 全量重嵌向量层，单测必须隔离——项目测试纪律）。
    """
    from competitor_agent.config.loader import AppConfig
    from competitor_agent.domain_types.report import ComparisonReport
    from competitor_agent.facade.api import CompetitorAnalysisAPI

    cfg = AppConfig()
    cfg.report.export_json = True
    api = CompetitorAnalysisAPI(config=cfg, enable_rag=False)
    survey = ComparisonReport(
        competitors=[],
        reports=[],
        markdown_report="未收集到候选数据，对比矩阵为空。\n",
    )
    assert api._export_comparison_json(survey) is None
