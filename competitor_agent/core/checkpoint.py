"""Checkpoint — 会话断点续跑/中断支持

将分析过程中的中间状态（缺口进度、已采集数据、预算状态）序列化到 JSON，
支持中断后从 checkpoint 恢复继续分析。

数据目录：``~/.competitor_agent/checkpoints/``
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import GapStatus
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import SourceEvidence
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult
from competitor_agent.secret_vault import get_data_dir

logger = logging.getLogger("competitor_agent.core.checkpoint")

_CHECKPOINT_DIR = get_data_dir() / "checkpoints"
_CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

# 全局取消标志
_cancel_flags: dict[str, bool] = {}
_cancel_lock = threading.Lock()


@dataclass
class Checkpoint:
    """分析会话的中间状态快照"""

    session_id: str
    task: str
    competitor_name: str
    created_at: str
    updated_at: str

    # 缺口进度
    gaps: list[dict[str, Any]] = field(default_factory=list)
    # 已完成维度结果
    dimension_results: list[dict[str, Any]] = field(default_factory=list)
    # 预算状态
    iterations_used: int = 0
    max_iterations: int = 10
    cost_used: float = 0.0
    cost_limit: float = 1.0
    # 已尝试数据源
    sources_tried: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        return cls(**data)


def _checkpoint_path(session_id: str) -> Path:
    return _CHECKPOINT_DIR / f"{session_id}.json"


def save_checkpoint(
    session_id: str,
    task: str,
    competitor_name: str,
    gaps: list[InfoGap],
    dimension_results: list[DimensionResult],
    iterations_used: int,
    max_iterations: int,
    cost_used: float,
    cost_limit: float,
    sources_tried: list[str],
) -> Checkpoint:
    """保存分析会话的 checkpoint"""
    now = datetime.now(timezone.utc).isoformat()
    cp = Checkpoint(
        session_id=session_id,
        task=task,
        competitor_name=competitor_name,
        created_at=now,
        updated_at=now,
        gaps=[g.to_dict() for g in gaps],
        dimension_results=[
            {
                "dimension": r.dimension,
                "summary": r.summary,
                "details": r.details,
                "confidence": r.confidence,
                "evidence": [
                    {
                        "source_name": e.source_name,
                        "url": e.url,
                        "access_time": e.access_time,
                        "content_hash": e.content_hash,
                        "trust_level": e.trust_level,
                    }
                    for e in r.evidence
                ],
                "timestamp": r.timestamp,
                "status": r.status.value,
            }
            for r in dimension_results
        ],
        iterations_used=iterations_used,
        max_iterations=max_iterations,
        cost_used=cost_used,
        cost_limit=cost_limit,
        sources_tried=sources_tried,
    )
    path = _checkpoint_path(session_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cp.to_dict(), f, ensure_ascii=False, indent=2)
    logger.info("Checkpoint 已保存: %s (%d gaps, %d results)", session_id, len(gaps), len(dimension_results))
    return cp


def load_checkpoint(session_id: str) -> Checkpoint | None:
    """加载 checkpoint"""
    path = _checkpoint_path(session_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Checkpoint.from_dict(data)
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Checkpoint 加载失败 %s: %s", session_id, e)
        return None


def delete_checkpoint(session_id: str) -> None:
    """删除 checkpoint（分析完成后清理）"""
    path = _checkpoint_path(session_id)
    if path.exists():
        path.unlink()
        logger.info("Checkpoint 已删除: %s", session_id)


def list_checkpoints() -> list[Checkpoint]:
    """列出所有 checkpoint"""
    result: list[Checkpoint] = []
    for path in sorted(_CHECKPOINT_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            result.append(Checkpoint.from_dict(data))
        except (json.JSONDecodeError, KeyError):
            continue
    return result


def checkpoint_to_report(cp: Checkpoint) -> CompetitorReport:
    """将 checkpoint 恢复为 CompetitorReport（供 resume 返回）"""
    from competitor_agent.core.report_builder import ReportBuilder
    from competitor_agent.domain_types.enums import ResultStatus

    competitor = Competitor(name=cp.competitor_name)
    results = []
    for r in cp.dimension_results:
        evidence = [
            SourceEvidence(
                source_name=e["source_name"],
                url=e.get("url", ""),
                access_time=e.get("access_time", ""),
                content_hash=e.get("content_hash", ""),
                trust_level=e.get("trust_level", 0.5),
            )
            for e in r.get("evidence", [])
        ]
        results.append(
            DimensionResult(
                dimension=r["dimension"],
                summary=r.get("summary", ""),
                details=r.get("details", {}),
                confidence=r.get("confidence", 0.0),
                evidence=evidence,
                timestamp=r.get("timestamp", ""),
                status=ResultStatus(r.get("status", "partial")),
            )
        )

    gaps = []
    for g in cp.gaps:
        gap = InfoGap(
            field=g["field"],
            priority=g.get("priority", 5),
            confidence=g.get("confidence", 0.0),
            sources_tried=g.get("sources_tried", []),
            status=GapStatus(g.get("status", "open")),
        )
        for ev in g.get("evidence", []):
            gap.add_evidence(
                SourceEvidence(
                    source_name=ev.get("source_name", ""),
                    url=ev.get("url", ""),
                    content_hash=ev.get("content_hash", ""),
                    trust_level=ev.get("trust_level", 0.5),
                )
            )
        gaps.append(gap)

    builder = ReportBuilder()
    report = builder.build(
        competitor=competitor,
        results=results,
        gaps_pending=[g for g in gaps if not g.is_closed],
        terminal_state="partial",
    )
    return report


# ── 取消标志 ──────────────────────────────────────────────────────────────

def set_cancel(session_id: str) -> None:
    """设置取消标志"""
    with _cancel_lock:
        _cancel_flags[session_id] = True


def is_cancelled(session_id: str) -> bool:
    """检查是否被取消"""
    with _cancel_lock:
        return _cancel_flags.get(session_id, False)


def clear_cancel(session_id: str) -> None:
    """清除取消标志"""
    with _cancel_lock:
        _cancel_flags.pop(session_id, None)
