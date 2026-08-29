"""ComparisonReport 组装器（设计文档 62 §3.5）— 从单 Lead loop 产物组装对比/发现报告

数据源（全部来自同一条单 Lead loop，无第二次 LLM 调用）：
- ``candidate_results``：delegate 收集器落盘的候选子 Agent 标准多维度 ``dimensions[]``
  （``{competitor, dimensions, official_links}``，对齐 REPORT_SCHEMA）；
- ``plan``：``plan.resolution`` 决定分型（compare/discovery）与候选排序；
- ``lead_answer``：Lead Final Answer 的【市场格局核心结论】段。

职责：每候选 ``dimensions[]`` → 最小 CompetitorReport → ``build_comparison`` 渲染
"维度 × 竞品"矩阵（执行层，不经 LLM）；Lead 结论段拼入。候选缺失/结论缺失时
矩阵与结论段各自兜底不报错。

设计文档 65 §2.3：``_extract_conclusion`` 复用 ``_extract_json_block``（括号配平），
兼容"散文前缀 + JSON"形态的 Lead Final Answer（不再要求整体以 ``{`` 开头）。
"""
from __future__ import annotations

from typing import Any

from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.report import ComparisonReport, CompetitorReport

_MARKER = "【市场格局核心结论】"


def assemble_comparison(
    lead_answer: str,
    plan: dict[str, Any] | None,
    candidate_results: dict[str, dict[str, Any]],
    builder: Any | None = None,
    terminal_state: str = "success",
) -> ComparisonReport:
    """把候选 ``dimensions[]`` + Lead 结论组装为 ComparisonReport。

    - 每候选 ``dimensions[]`` 组装为最小 CompetitorReport（复用什么 ``_dimension_from_item``
      的维度条目解析与置信度封顶兜底）；
    - 矩阵按 ``plan.competitors`` 顺序渲染（缺 plan 时按收集顺序）；
    - Lead Final Answer 的结论段拼入 ``## 市场格局核心结论`` 区。
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

    conclusion = _extract_conclusion(lead_answer)
    if conclusion:
        comparison.markdown_report = (
            comparison.markdown_report.rstrip()
            + "\n\n## 市场格局核心结论\n\n"
            + conclusion
            + "\n"
        )
    return comparison


def _extract_conclusion(lead_answer: str) -> str:
    """从 Lead Final Answer 提取市场格局核心结论段。

    - comparison JSON（含 ``conclusion`` 字段）→ 取字段值（设计文档 65 §2.3：
      复用 ``_extract_json_block`` 括号配平提取，兼容散文前缀形态）；
    - 文本含【市场格局核心结论】标记 → 取标记后内容；
    - 其余文本 → 整段作为结论；JSON 无 conclusion 字段 → 空（矩阵兜底）。
    """
    from competitor_agent.facade.react_report import _extract_json_block

    text = (lead_answer or "").strip()
    if not text:
        return ""
    for prefix in ("Final Answer: ", "Final Answer:"):
        if text.startswith(prefix):
            text = text[len(prefix):].lstrip()
            break
    if _MARKER in text:
        return text.split(_MARKER, 1)[1].strip()
    payload = _extract_json_block(text)
    if isinstance(payload, dict):
        if payload.get("conclusion"):
            return str(payload["conclusion"])
        return ""
    return text


__all__ = ["_extract_conclusion", "assemble_comparison"]
