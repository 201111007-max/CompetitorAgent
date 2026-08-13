"""竞品异动告警（设计文档 28 §3.3）

``Alert`` 描述一次竞品变化（价格 / 功能 / 版本 / 榜单 / 路线图）；``AlertSink``
为输出协议，``FileAlertSink`` 追加写入 ``reports/alerts/<date>.md``（控制台可用
``ConsoleAlertSink``）。``report_diff`` 复用设计文档 26 的 ``TimelineMemory.diff``
把时间线事件映射为告警。
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

logger = logging.getLogger("competitor_agent.core.alerting")

# 时间线事件类型 → 告警 kind（缺失时保留事件类型名）
_EVENT_KIND = {
    "price_change": "price_change",
    "feature_added": "feature_added",
    "version_release": "version_release",
    "score_change": "score_change",
}


@dataclass
class Alert:
    """一条竞品异动告警"""

    competitor: str
    kind: str  # price_change / feature_added / version_release / score_change / roadmap_update
    summary: str
    old_value: str = ""
    new_value: str = ""
    evidence_urls: list[str] = field(default_factory=list)
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AlertSink(Protocol):
    """告警输出协议"""

    def emit(self, alert: Alert) -> None: ...


class ConsoleAlertSink:
    """打印告警到控制台（CRON/脚本场景可视化）"""

    def emit(self, alert: Alert) -> None:
        print(f"[alert:{alert.kind}] {alert.competitor}: {alert.summary}", flush=True)


class FileAlertSink:
    """追加写入 reports/alerts/<date>.md（按日聚合，线程安全追加）。"""

    def __init__(self, output_dir: str | Path | None = None) -> None:
        self._dir = Path(output_dir).expanduser() if output_dir else Path("reports/alerts")
        self._lock = threading.Lock()

    def _resolve(self) -> Path:
        path = self._dir
        return path if path.is_absolute() else Path.cwd() / path

    def emit(self, alert: Alert) -> None:
        out_dir = self._resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        date = str(alert.occurred_at)[:10]
        path = out_dir / f"{date}.md"
        lines = [
            f"- [{alert.kind}] **{alert.competitor}**: {alert.summary}",
        ]
        if alert.old_value or alert.new_value:
            lines.append(f"  变化: {alert.old_value or '-'} → {alert.new_value or '-'}")
        if alert.evidence_urls:
            lines.append(f"  证据: {', '.join(str(u) for u in alert.evidence_urls[:3])}")
        with self._lock, open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def _alert_from_event(event: object) -> Alert:
    """时间线事件 → 告警（复用设计文档 26 的事件字段）。"""
    summary = str(getattr(event, "summary", "") or "")
    kind = _EVENT_KIND.get(str(getattr(event, "event_type", "")), str(getattr(event, "event_type", "")))
    old_value = str(getattr(event, "diff_from", "") or "")
    return Alert(
        competitor=str(getattr(event, "competitor", "") or ""),
        kind=kind,
        summary=summary,
        old_value=old_value,
        new_value=str(getattr(event, "occurred_at", "") or "")[:10],
        evidence_urls=list(getattr(event, "evidence_urls", []) or []),
        occurred_at=str(getattr(event, "occurred_at", "") or "") or datetime.now(timezone.utc).isoformat(),
    )


def report_diff(prev: object, cur: object) -> list[Alert]:
    """两份报告维度级 diff → 告警列表（复用 TimelineMemory.diff 的事件映射）。

    无变化（或 prev 无基线）返回空列表。prev/cur 为 CompetitorReport 或
    duck-type（dimension_results / competitor.name），与 TimelineMemory.diff 一致。
    """
    from competitor_agent.memory.timeline_memory import TimelineMemory

    events = TimelineMemory.diff(prev, cur)  # type: ignore[arg-type]
    return [_alert_from_event(e) for e in events]


__all__ = ["Alert", "AlertSink", "ConsoleAlertSink", "FileAlertSink", "report_diff"]
