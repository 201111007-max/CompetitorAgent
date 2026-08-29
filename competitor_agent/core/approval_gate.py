"""human-in-the-loop 审批节点（设计文档 67 §3.2）

状态机：``draft → pending_review → approved / rejected``（rejected 附原因回灌注释）。

- ``ApprovalPolicy``（可配置）：低置信 / price_change / score_change / 新增竞品等
  触发规则；未命中规则 → 直通 ``approved``（不打扰）；
- 落盘：报告 JSON 增 ``status`` / ``reviewed_at`` / ``reviewer_note`` 字段
  （``report_to_dict`` 扩展，向后兼容旧 JSON——无 status 字段读为 ``approved``）；
- CLI ``report --approve/--reject`` 与 Web ``/api/reports/{name}/review`` 共用
  ``set_report_status`` 读写报告 JSON（原子写，复用 checkpoint 模式）。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from competitor_agent.core.checkpoint import _write_bytes_atomic

logger = logging.getLogger("competitor_agent.core.approval_gate")

APPROVED = "approved"
PENDING_REVIEW = "pending_review"
REJECTED = "rejected"
DRAFT = "draft"

# 旧 JSON（无 status 字段）向后兼容读为 approved
_DEFAULT_STATUS = APPROVED


@dataclass
class ApprovalPolicy:
    """审批触发规则（可配置，未命中 → 直通 approved 不打扰）。"""

    review_low_confidence: bool = True  # 任一维度 PARTIAL 低置信 / 整体低置信
    low_confidence_threshold: float = 0.4
    review_price_change: bool = True  # 本周价格变动（时间线 price_change 事件）
    review_score_change: bool = True  # 榜单分数变化（score_change 事件）
    review_new_competitor: bool = True  # 新增竞品（无先前基线）


def decide_approval(
    report: object,
    *,
    timeline_events: list[object] | None = None,
    is_new_competitor: bool = False,
    policy: ApprovalPolicy | None = None,
) -> str:
    """报告是否触发人工审批 → ``pending_review`` 或 ``approved``。

    ``report`` 为 CompetitorReport（duck-type：overall_confidence /
    dimension_results）；``timeline_events`` 为本次时间线 diff 事件
    （TimelineEvent，含 ``event_type``）；``is_new_competitor`` 无先前基线。
    """
    policy = policy or ApprovalPolicy()
    overall = float(getattr(report, "overall_confidence", 0.0) or 0.0)
    threshold = policy.low_confidence_threshold

    if policy.review_low_confidence:
        if overall < threshold:
            return PENDING_REVIEW
        for r in getattr(report, "dimension_results", []) or []:
            status = getattr(r, "status", None)
            status_val = getattr(status, "value", None) or str(status)
            conf = float(getattr(r, "confidence", 0.0) or 0.0)
            if status_val == "partial" and conf < threshold:
                return PENDING_REVIEW

    if policy.review_new_competitor and is_new_competitor:
        return PENDING_REVIEW

    if policy.review_price_change or policy.review_score_change:
        for e in timeline_events or []:
            kind = str(getattr(e, "event_type", "") or "")
            if kind == "price_change" and policy.review_price_change:
                return PENDING_REVIEW
            if kind == "score_change" and policy.review_score_change:
                return PENDING_REVIEW

    return APPROVED


def decide_weekly_approval(
    weekly_data: dict[str, Any],
    policy: ApprovalPolicy | None = None,
) -> str:
    """周报审批：含 high-impact 项（价格/榜单/新增竞品）→ pending_review，否则 approved。"""
    policy = policy or ApprovalPolicy()
    if not policy.review_price_change and not policy.review_score_change and not policy.review_new_competitor:
        return APPROVED
    return PENDING_REVIEW if weekly_data.get("high_impact") else APPROVED


def report_status(json_path: str | Path) -> str:
    """读报告 JSON 的 status 字段；无 status（旧 JSON）向后兼容读为 approved。"""
    try:
        data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _DEFAULT_STATUS
    if not isinstance(data, dict):
        return _DEFAULT_STATUS
    return str(data.get("status") or _DEFAULT_STATUS)


def set_report_status(
    json_path: str | Path,
    status: str,
    reviewer_note: str = "",
) -> dict[str, Any]:
    """写报告 JSON 的 status/reviewed_at/reviewer_note（原子写），返回更新后数据。

    ``status`` 限 approved / rejected / pending_review；非法值抛 ValueError。
    """
    if status not in (APPROVED, REJECTED, PENDING_REVIEW):
        raise ValueError(f"非法审批状态: {status!r}（可选 approved | rejected | pending_review）")
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"报告 JSON 不存在: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"报告 JSON 解析失败: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TypeError(f"报告 JSON 非对象: {path}")
    data["status"] = status
    data["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    data["reviewer_note"] = reviewer_note
    _write_bytes_atomic(path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    logger.info("报告审批状态更新: %s → %s", path, status)
    return data


def report_json_path(competitor: str, output_dir: str | Path | None = None) -> Path:
    """解析竞品报告 JSON 落盘路径（与 export_competitor_json 命名一致）。

    设计文档 70：新目录优先；未显式指定目录时旧归档
    （~/.competitor_agent/reports/competitor）读侧回退（历史报告 JSON 审批状态不丢）。
    显式 output_dir → 精确路径，不回退。均不存在 → 返回新目录路径（由调用方 404/缺省）。
    """
    from competitor_agent.core.report_archiver import _safe_filename, resolve_output_dir

    primary = resolve_output_dir(output_dir) / (_safe_filename(competitor) + ".json")
    if primary.exists():
        return primary
    if output_dir is None:
        legacy = Path("~/.competitor_agent/reports/competitor").expanduser() / (
            _safe_filename(competitor) + ".json"
        )
        if legacy.exists():
            return legacy
    return primary


__all__ = [
    "APPROVED",
    "DRAFT",
    "PENDING_REVIEW",
    "REJECTED",
    "ApprovalPolicy",
    "decide_approval",
    "decide_weekly_approval",
    "report_json_path",
    "report_status",
    "set_report_status",
]
