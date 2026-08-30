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

# 设计文档 70 §8.1 D1d：零候选空报告仍落盘 .md（内容 = 提示），不额外制造垃圾——
# 矩阵空 + Lead 结论段 + 本提示，报告库可见可点开看原因。
_ZERO_CANDIDATE_HINT = (
    "未收集到候选数据（候选委派超时/失败），对比矩阵为空，置信度 0% 为事实。"
)


def assemble_comparison(
    lead_answer: str,
    plan: dict[str, Any] | None,
    candidate_results: dict[str, dict[str, Any]],
    builder: Any | None = None,
    terminal_state: str = "success",
    use_lead_body: bool | None = None,
) -> ComparisonReport:
    """把候选 ``dimensions[]`` + Lead 结论组装为 ComparisonReport。

    - 每候选 ``dimensions[]`` 组装为最小 CompetitorReport（复用什么 ``_dimension_from_item``
      的维度条目解析与置信度封顶兜底）；
    - 矩阵按 ``plan.competitors`` 顺序渲染（缺 plan 时按收集顺序）；
    - 设计文档 70 M1：Lead Final Answer 正文（剔除 JSON 块后的纯散文，含结论段）在前、
      代码矩阵附录在后（信息不丢）；正文为空（mock 纯 JSON）→ 保留矩阵 + 提取
      ``## 市场格局核心结论`` 段（现状行为，确定性不变）。
    """
    from competitor_agent.core.report_builder import ReportBuilder
    from competitor_agent.facade.react_report import _dimension_from_item

    builder = builder or ReportBuilder()
    if use_lead_body is None:
        from competitor_agent.config.loader import load_config

        use_lead_body = load_config().report.lead_formatted_body
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
    if use_lead_body:
        lead_body = _lead_body_text(lead_answer)
        if lead_body:
            # 设计文档 70 M1：Lead 正文在前、代码矩阵附录在后（信息不丢、前端零改动）
            comparison.markdown_report = (
                lead_body
                + "\n\n"
                + (comparison.markdown_report or "").strip()
                + "\n"
            )
    if not comparison.markdown_report.strip():
        # 设计文档 70 §8.1 D1d：零候选且无正文/结论 → 提示留痕，保证 .md 非空可落盘
        comparison.markdown_report = _ZERO_CANDIDATE_HINT + "\n"
    elif not reports and _ZERO_CANDIDATE_HINT not in comparison.markdown_report:
        # 零候选但有 Lead 正文/结论 → 正文/结论在前、提示追加在后（"矩阵空 + 结论段 + 提示"）
        comparison.markdown_report = (
            comparison.markdown_report.rstrip() + "\n\n" + _ZERO_CANDIDATE_HINT + "\n"
        )
    if conclusion and "## 市场格局核心结论" not in comparison.markdown_report:
        comparison.markdown_report = (
            comparison.markdown_report.rstrip()
            + "\n\n## 市场格局核心结论\n\n"
            + conclusion
            + "\n"
        )
    return comparison


def _lead_body_text(lead_answer: str) -> str:
    """提取 Lead Final Answer 的正文（设计文档 70 M1）：剔除对比 JSON 块 + 去 Final Answer 前缀。

    正文为空（mock 纯 JSON）→ 空串 → 调用方回退矩阵 + 结论段（确定性不变）。
    """
    from competitor_agent.facade.react_report import _strip_json_blocks

    text = _strip_json_blocks(lead_answer or "").strip()
    for prefix in ("Final Answer: ", "Final Answer:"):
        if text.startswith(prefix):
            text = text[len(prefix):].lstrip()
            break
    return text


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