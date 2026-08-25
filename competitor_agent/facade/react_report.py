"""Lead Final Answer → CompetitorReport 组装（设计文档 49 §3.4）

解析 Lead 的 REPORT_SCHEMA JSON（competitor + dimensions[{dimension, summary,
details, confidence, evidence_urls}]）→ 多维度 ``DimensionResult`` → CompetitorReport
（复用 ``ReportBuilder`` 渲染/freshness）。

兜底：
- 非 JSON / 缺 dimensions → 单 ``react`` 维度 PARTIAL（解析健壮性，非规则决策）；
- 数值真值核对：details 非空但无证据 URL 的维度 → 置信度封顶 0.5 并标注；
- 跨维度同源冲突（按证据 URL 键，``detect_conflicts_across``）→ 报告追加
  「## 跨维度冲突备注」（复用 49 旧版渲染约定）；
- plan 中声明但报告未产出的维度 → ``gaps_pending`` 列明（供 resume/预算判定）。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import GapStatus, ResultStatus
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import SourceEvidence
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult
from competitor_agent.observability.logger import get_logger

logger = get_logger("facade.react_report")

# details 非空但零证据 URL 的维度：置信度封顶（防无来源断言）
_MAX_CONFIDENCE_NO_EVIDENCE = 0.5


def assemble(
    lead_answer: str,
    competitor: Competitor,
    loop_plan: dict[str, Any] | None,
    transcript: list[dict] | None = None,
    builder: Any | None = None,
    terminal_state: str = "success",
) -> CompetitorReport:
    """把 Lead Final Answer 组装为 CompetitorReport。"""
    from competitor_agent.core.report_builder import ReportBuilder

    builder = builder or ReportBuilder()
    payload = _parse_report(lead_answer)
    if payload is None:
        return _fallback_single_dimension(lead_answer, competitor, builder, terminal_state, loop_plan)

    dimensions: list[DimensionResult] = []
    for item in payload.get("dimensions") or []:
        dr = _dimension_from_item(item)
        if dr is not None:
            dimensions.append(dr)

    # 跨维度同源冲突兜底（按证据 URL 键，代码强制，不进 LLM 决策）
    conflict_note = ""
    if dimensions:
        try:
            from competitor_agent.domain_types.conflict import detect_conflicts_across

            conflicts = detect_conflicts_across(
                [
                    {
                        "dimension": d.dimension,
                        "details": d.details,
                        "evidence_urls": [e.url for e in d.evidence],
                    }
                    for d in dimensions
                ]
            )
            if conflicts:
                lines = [f"- {c.summary}" for c in conflicts]
                conflict_note = "## 跨维度冲突备注\n\n" + "\n".join(lines) + "\n"
        except Exception:
            logger.warning("跨维度冲突检测失败，跳过", exc_info=True)

    # plan 声明但未产出的维度 → gaps_pending（供 resume/预算/报告标注）
    planned = _planned_dimensions(loop_plan)
    produced = {d.dimension for d in dimensions}
    missing = [dim for dim in planned if dim not in produced]
    gaps_pending = [InfoGap(field=dim, priority=5, status=GapStatus.PARTIAL) for dim in missing]

    report = builder.build(
        competitor=competitor,
        results=dimensions,
        gaps_pending=gaps_pending,
        terminal_state=terminal_state,
    )
    if conflict_note and report.markdown_report:
        report.markdown_report = report.markdown_report.rstrip() + "\n\n" + conflict_note
    return report


def _parse_report(answer: str) -> dict[str, Any] | None:
    """解析 REPORT_SCHEMA JSON；非 JSON/缺 dimensions → None。"""
    text = (answer or "").strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict) and isinstance(payload.get("dimensions"), list):
            return payload
    return None


def _dimension_from_item(item: dict[str, Any]) -> DimensionResult | None:
    dim = str(item.get("dimension") or "").strip()
    if not dim:
        return None
    summary = str(item.get("summary") or "")
    raw_details = item.get("details")
    details: dict[str, Any] = raw_details if isinstance(raw_details, dict) else {}
    raw_confidence = item.get("confidence")
    confidence = 0.5
    if raw_confidence is not None:
        try:
            confidence = max(0.0, min(1.0, float(raw_confidence)))
        except (TypeError, ValueError):
            confidence = 0.5
    urls = [str(u) for u in (item.get("evidence_urls") or []) if u]
    # 数值真值核对兜底：details 非空但零证据 → 置信度封顶并标注（防无来源断言）
    if details and not urls:
        confidence = min(confidence, _MAX_CONFIDENCE_NO_EVIDENCE)
    evidence = [
        SourceEvidence(
            source_name="web",
            url=url,
            access_time=datetime.now(timezone.utc).isoformat(),
            trust_level=0.8,
        )
        for url in urls
    ]
    return DimensionResult(
        dimension=dim,
        summary=summary,
        details=details,
        confidence=confidence,
        evidence=evidence,
        status=ResultStatus.COMPLETE if confidence >= 0.5 else ResultStatus.PARTIAL,
        # 证据链（设计文档 49 §3.1）：无 content_hash，以 URL 代理（跨维度冲突按 URL 键）
        evidence_hashes=list(urls),
    )


def _planned_dimensions(loop_plan: dict[str, Any] | None) -> list[str]:
    if not isinstance(loop_plan, dict):
        return []
    dims = loop_plan.get("dimensions")
    if isinstance(dims, list):
        return [str(d) for d in dims if d]
    return []


def _fallback_single_dimension(
    answer: str,
    competitor: Competitor,
    builder: Any,
    terminal_state: str,
    loop_plan: dict[str, Any] | None = None,
) -> CompetitorReport:
    """非 JSON / 无 dimensions：单 react 维度 PARTIAL（LLM 不可用/超步数文案）。

    plan 已声明但未产出的维度 → gaps_pending（供 resume/预算判定），与
    assemble() 正常路径一致。
    """
    text = (answer or "").strip()
    is_unavailable = "LLM 服务不可用" in text or "已达最大" in text or "推理已停止" in text
    status = ResultStatus.PARTIAL
    confidence = 0.1 if is_unavailable else 0.4
    dr = DimensionResult(
        dimension="react",
        summary=text or "（Lead Agent 未产出结构化结论）",
        details={},
        confidence=confidence,
        status=status,
    )
    planned = _planned_dimensions(loop_plan)
    gaps_pending = [InfoGap(field=dim, priority=5, status=GapStatus.PARTIAL) for dim in planned]
    return builder.build(
        competitor=competitor,
        results=[dr],
        gaps_pending=gaps_pending,
        terminal_state=terminal_state,
    )
