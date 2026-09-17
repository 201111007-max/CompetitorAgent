"""ComparisonReport 组装器（设计文档 62 §3.5）— 从单 Lead loop 产物组装对比/发现报告

数据源（全部来自同一条单 Lead loop）：
- ``candidate_results``：delegate 收集器落盘的候选子 Agent 标准多维度 ``dimensions[]``
  （``{competitor, dimensions, official_links}``，对齐 REPORT_SCHEMA）；
- ``plan``：``plan.resolution`` 决定分型（compare/discovery）与候选排序。

职责：每候选 ``dimensions[]`` → 最小 CompetitorReport → ``build_comparison`` 渲染
"维度 × 竞品"矩阵（执行层，不经 LLM）。候选缺失时矩阵兜底不报错。

设计文档 95：Lead Final Answer 从报告链路退役——「## 市场格局核心结论」段的唯一
合法来源 = writer LLM 从蒸馏事实生成的 prose（``writer_pass.maybe_run_comparison_writer_pass``，
由 ``compare_service._finalize_comparison_report`` 接线），组装层不再解析 Lead 文本
（原 ``_extract_conclusion`` 的解析兜底正是 JSON 泄漏入口，整体删除）。
"""
from __future__ import annotations

from typing import Any

from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.report import ComparisonReport, CompetitorReport

# 设计文档 70 §8.1 D1d：零候选空报告仍落盘 .md（内容 = 提示），不额外制造垃圾——
# 矩阵空 + 本提示，报告库可见可点开看原因。
# 文案中性化：不臆断「超时/失败」（可能是未委派候选或结果未收集），也不展示置信度。
_ZERO_CANDIDATE_HINT = "未收集到候选数据，对比矩阵为空。"


def assemble_comparison(
    plan: dict[str, Any] | None,
    candidate_results: dict[str, dict[str, Any]],
    builder: Any | None = None,
    terminal_state: str = "success",
) -> ComparisonReport:
    """把候选 ``dimensions[]`` 组装为 ComparisonReport。

    - 每候选 ``dimensions[]`` 组装为最小 CompetitorReport（复用什么 ``_dimension_from_item``
      的维度条目解析与置信度封顶兜底）；
    - 矩阵按 ``plan.competitors`` 顺序渲染（缺 plan 时按收集顺序）；
    - 设计文档 95：结论段不再在本层拼接（writer 通道另行追加，矩阵自身说话）。
    """
    from competitor_agent.core.report_builder import ReportBuilder
    from competitor_agent.facade.react_report import _dimension_from_item

    builder = builder or ReportBuilder()
    per_candidate: dict[str, CompetitorReport] = {}
    for name, payload in candidate_results.items():
        dims = [d for d in (payload.get("dimensions") or []) if isinstance(d, dict)]
        dim_results = [
            dr for item in dims if (dr := _dimension_from_item(item)) is not None
        ]
        comp_name = str(payload.get("competitor") or name).strip() or name
        per_candidate[name] = builder.build(
            competitor=Competitor(name=comp_name),
            results=dim_results,
            gaps_pending=[],
            terminal_state=terminal_state,
        )

    ordered: list[str] = []
    plan_competitors = [str(c) for c in ((plan or {}).get("competitors") or [])]
    if plan_competitors:
        ordered = [c for c in plan_competitors if c in per_candidate]
        ordered += [n for n in per_candidate if n not in ordered]
    else:
        ordered = list(per_candidate)
    reports = [per_candidate[n] for n in ordered]

    if reports:
        comparison = builder.build_comparison(reports)
    else:
        # 无候选结果：空矩阵兜底（aggregate_report/delegate 缺失不报错，设计文档 62 §5）
        comparison = ComparisonReport(competitors=[], reports=[], markdown_report="")

    if not comparison.markdown_report.strip():
        # 设计文档 70 §8.1 D1d：零候选无正文 → 提示留痕，保证 .md 非空可落盘
        comparison.markdown_report = _ZERO_CANDIDATE_HINT + "\n"
    return comparison


__all__ = ["assemble_comparison"]
