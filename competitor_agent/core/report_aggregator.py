"""研究员结果聚合层（设计文档 88 §4.1，N1）

代码确定性合并：各研究员（维度子 Agent）的 ``_DIMENSION_RESULT_ITEM`` 逐条解析
（``dimension_from_item``，沿用置信度夹取/无证据封顶/evidence_urls 归一）→
跨维度同源冲突检测（``detect_conflicts_across``）→ planned/produced 对账
（plan 声明但未产出 → ``gaps_pending``）。**无 LLM 调用**——消灭 Lead LLM 再聚合环节。

本模块为 ``facade/react_report.assemble`` 聚合逻辑的纯平移（语义不变）；
react_report 保留私有名别名供 comparison_report 与既有测试引用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from competitor_agent.core.json_extract import coerce_str_list
from competitor_agent.domain_types.enums import GapStatus, ResultStatus
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import SourceEvidence
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.observability.logger import get_logger

logger = get_logger("core.report_aggregator")

# details 非空但零证据 URL 的维度：置信度封顶（防无来源断言）
MAX_CONFIDENCE_NO_EVIDENCE = 0.5


@dataclass
class AggregateResult:
    """聚合产物：维度结果 + 未产出缺口 + 跨维度冲突备注（markdown，可为空）。"""

    dimensions: list[DimensionResult] = field(default_factory=list)
    gaps_pending: list[InfoGap] = field(default_factory=list)
    conflict_note: str = ""


def aggregate_researcher_results(
    items: list[dict[str, Any]],
    loop_plan: dict[str, Any] | None,
) -> AggregateResult:
    """确定性合并研究员 JSON（设计文档 88 §9.3：合并是纯数据操作，不经 LLM）。

    - 逐条 ``dimension_from_item``（缺 dimension 名的条目跳过）；
    - 跨维度同源冲突兜底（按证据 URL 键，代码强制，不进 LLM 决策），命中时
      生成「## 跨维度冲突备注」markdown 段（复用 49 旧版渲染约定）；
    - plan 中声明但未产出的维度 → ``gaps_pending``（供 resume/预算判定）。
    """
    dimensions: list[DimensionResult] = []
    for item in items:
        dr = dimension_from_item(item)
        if dr is not None:
            dimensions.append(dr)

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

    planned = planned_dimensions(loop_plan)
    produced = {d.dimension for d in dimensions}
    missing = [dim for dim in planned if dim not in produced]
    gaps_pending = [InfoGap(field=dim, priority=5, status=GapStatus.PARTIAL) for dim in missing]

    return AggregateResult(
        dimensions=dimensions, gaps_pending=gaps_pending, conflict_note=conflict_note
    )


def dimension_from_item(item: dict[str, Any]) -> DimensionResult | None:
    """单条 ``_DIMENSION_RESULT_ITEM`` → DimensionResult（置信度夹取/封顶/URL 归一）。"""
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
    # 设计文档 87 §1.4-C1：evidence_urls 归一——模型返回单个字符串 URL 时按整体一项，
    # 不再被按字符迭代成 "h","t","t","p" 垃圾证据
    urls = coerce_str_list(item.get("evidence_urls"))
    # 数值真值核对兜底：details 非空但零证据 → 置信度封顶并标注（防无来源断言）
    if details and not urls:
        confidence = min(confidence, MAX_CONFIDENCE_NO_EVIDENCE)
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


def planned_dimensions(loop_plan: dict[str, Any] | None) -> list[str]:
    """loop_plan 中声明的维度列表（对账基准）。"""
    if not isinstance(loop_plan, dict):
        return []
    dims = loop_plan.get("dimensions")
    if isinstance(dims, list):
        return [str(d) for d in dims if d]
    return []
