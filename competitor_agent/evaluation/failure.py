"""失败类型分类（设计文档 31）：把未命中 case / 缺陷归入五类之一

回答「这个 case 为什么没命中？」，支撑归因优化与简历/面试的"失败类型统计"证据：
- source_unavailable：源抓取失败 / 降级链全灭 / BLOCKED；
- hallucination：预测字段无真值支持（命中 accuracy_eval 的幻觉判定）；
- no_data：源有响应但内容不含目标信息（低置信 / [N/A]）；
- parse_failure：源有内容但抽取/归一化错误（预测非空但 F1 < 1 且非幻觉）；
- budget_exhausted：预算 / 迭代耗尽提前终止。

判定口径与 `accuracy_eval` 完全一致（复用其归一化），保证幻觉计数与
hallucination_instances 一一对应。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from competitor_agent.evaluation.accuracy_eval import _normalize, _tokens


class FailureType(str, Enum):
    SOURCE_UNAVAILABLE = "source_unavailable"
    HALLUCINATION = "hallucination"
    NO_DATA = "no_data"
    PARSE_FAILURE = "parse_failure"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass
class FailureRecord:
    case_id: str
    dimension: str
    failure_type: FailureType
    detail: str = ""
    evidence_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "dimension": self.dimension,
            "failure_type": self.failure_type.value,
            "detail": self.detail,
            "evidence_urls": self.evidence_urls,
        }


def _is_hallucinated(pred: Any, truth: Any) -> bool:
    """与 accuracy_eval 的幻觉判定一致：预测非空但归一化后与真值无共享 token。"""
    if not str(pred).strip():
        return False
    np_ = _normalize(pred)
    if not np_:
        return True
    return not (set(np_.split()) & _tokens(_normalize(truth)))


def _evidence_urls(report: object) -> list[str]:
    """从报告维度结果收集证据 URL（去重保序）"""
    urls: list[str] = []
    if report is None:
        return urls
    for result in getattr(report, "dimension_results", None) or []:
        for evidence in getattr(result, "evidence", None) or []:
            url = getattr(evidence, "url", "")
            if url and url not in urls:
                urls.append(url)
    return urls


def classify_case(
    case: object,
    prediction: dict[str, Any],
    ground_truth: dict[str, Any],
    report: object | None = None,
    status_hints: dict[str, Any] | None = None,
) -> list[FailureRecord]:
    """单 case 归类（设计文档 31 §3.1）：未命中字段归入五类之一。

    优先级：幻觉 > 预算触停 > 源不可用/BLOCKED > 无数据 > 解析错误。
    - 全部字段命中 → 返回 []（非失败 case，由调用方/聚合跳过）；
    - status_hints 提供 classify_case 无法自行推导的信号：
      budget_exhausted（预算触停）、source_unavailable（源抓取失败）、
      blocked（缺口状态 BLOCKED）。
    """
    case_id = str(getattr(case, "case_id", "") or getattr(case, "task", ""))
    dimension = str(getattr(case, "dimension", ""))
    hints = status_hints or {}
    evidence = _evidence_urls(report)

    mismatched = [
        f for f, truth in ground_truth.items()
        if _normalize(prediction.get(f, "")) != _normalize(truth)
    ]
    if not mismatched:
        return []

    hallucinated = [f for f in mismatched if _is_hallucinated(prediction.get(f, ""), ground_truth[f])]
    if hallucinated:
        return [
            FailureRecord(
                case_id,
                dimension,
                FailureType.HALLUCINATION,
                detail=f"幻觉字段: {', '.join(hallucinated)}（预测无真值支持）",
                evidence_urls=evidence,
            )
        ]
    if hints.get("budget_exhausted"):
        return [
            FailureRecord(case_id, dimension, FailureType.BUDGET_EXHAUSTED, "预算/迭代耗尽提前终止", evidence)
        ]
    if hints.get("source_unavailable") or hints.get("blocked"):
        return [
            FailureRecord(
                case_id,
                dimension,
                FailureType.SOURCE_UNAVAILABLE,
                "源抓取失败或降级后仍无有效数据（BLOCKED）",
                evidence,
            )
        ]
    if not prediction or all(not str(v).strip() for v in prediction.values()):
        return [
            FailureRecord(
                case_id,
                dimension,
                FailureType.NO_DATA,
                "源有响应但内容不含目标信息（低置信/[N/A]，不编造）",
                evidence,
            )
        ]
    return [
        FailureRecord(
            case_id,
            dimension,
            FailureType.PARSE_FAILURE,
            "抽取/归一化错误：结构对上、值不对（非幻觉但未完全命中）",
            evidence,
        )
    ]


__all__ = ["FailureRecord", "FailureType", "classify_case"]
