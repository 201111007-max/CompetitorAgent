"""时间线记忆（设计文档 26 §3.4）

跨分析 diff：把"版本发布 / 功能新增 / 价格变化 / 榜单变化"记为时间线事件。
- 独立记忆类型，与四层记忆（L1-L4）并存，不破坏现有语义；
- 数据落盘 ``<data_dir>/memory/timeline.json``（复用 JsonStore 原子写）；
- ``diff()`` 为纯比较（测试用），``update()`` 对比上次快照并落盘（运行时用）。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from competitor_agent.domain_types.report import CompetitorReport
from competitor_agent.memory.json_store import JsonStore, now_iso

# 维度 → 事件类型映射
_EVENT_TYPE_BY_DIM: dict[str, str] = {
    "pricing": "price_change",
    "feature": "feature_added",
    "performance": "score_change",
    "roadmap": "version_release",
    "ecosystem": "version_release",
}


@dataclass
class TimelineEvent:
    """一条竞品变化时间线事件"""

    competitor: str
    event_type: str  # version_release / feature_added / price_change / score_change
    summary: str
    occurred_at: str = field(default_factory=now_iso)
    evidence_urls: list[str] = field(default_factory=list)
    diff_from: str = ""  # 与上一次的对比基线


def _snapshot_map(results: Sequence[object]) -> dict[str, dict[str, Any]]:
    """维度结果 → {dimension: {summary, details, timestamp, urls}}（diff 基线）。"""
    snap: dict[str, dict[str, Any]] = {}
    for r in results:
        dim = str(getattr(r, "dimension", ""))
        if not dim:
            continue
        evs = getattr(r, "evidence", None) or []
        urls = [str(getattr(e, "url", "")) for e in evs if getattr(e, "url", "")]
        snap[dim] = {
            "summary": str(getattr(r, "summary", "") or ""),
            "details": getattr(r, "details", None) or {},
            "timestamp": str(getattr(r, "timestamp", "") or ""),
            "urls": urls,
        }
    return snap


def _summarize_change(dim: str, prev: dict[str, Any], cur: dict[str, Any]) -> str:
    p = " ".join(str(prev.get("summary") or prev.get("details") or "").split())[:60]
    c = " ".join(str(cur.get("summary") or cur.get("details") or "").split())[:60]
    if p == c:
        return f"{dim} 发生变化（{_iso_short(cur.get('timestamp', ''))}）"
    return f"{dim}: {p} → {c}"


def _iso_short(value: str) -> str:
    return str(value)[:10] or ""


def _diff_snapshots(
    prev: dict[str, dict[str, Any]],
    cur: dict[str, dict[str, Any]],
    competitor: str,
) -> list[TimelineEvent]:
    """对比新旧快照：维度值变化 → 事件；无基线（首轮）不产生事件（防噪声）。"""
    events: list[TimelineEvent] = []
    for dim, c in cur.items():
        if dim not in prev:
            continue  # 首次出现的维度无对比基线，不产生事件
        p = prev[dim]
        if p.get("details") == c.get("details") and p.get("summary") == c.get("summary"):
            continue  # 同值不产生事件（防噪声）
        events.append(
            TimelineEvent(
                competitor=competitor,
                event_type=_EVENT_TYPE_BY_DIM.get(dim, "feature_added"),
                summary=_summarize_change(dim, p, c),
                occurred_at=c.get("timestamp") or now_iso(),
                evidence_urls=list(c.get("urls", [])),
                diff_from=_iso_short(p.get("timestamp", "")) or "",
            )
        )
    return events


class TimelineMemory:
    """跨分析 diff 的竞品时间线记忆（按竞品存快照 + 事件列表）。"""

    def __init__(self, data_dir: Any = None) -> None:
        self._store = JsonStore("timeline", data_dir)

    def append(self, event: TimelineEvent) -> None:
        """直接追加一条事件（外部事件，如手动记录）。"""
        bucket = self._bucket(event.competitor)
        bucket["events"].append(asdict(event))
        self._save_bucket(event.competitor, bucket)

    def events(self, competitor: str, limit: int = 20) -> list[TimelineEvent]:
        """取回某竞品最近事件（按 occurred_at 降序）。"""
        bucket = self._bucket(competitor)
        events = [_event_from_dict(e) for e in bucket.get("events", [])]
        events.sort(key=lambda e: e.occurred_at, reverse=True)
        return events[:limit]

    @staticmethod
    def diff(prev: CompetitorReport, cur: CompetitorReport) -> list[TimelineEvent]:
        """纯比较两份报告：维度级 diff → 事件（测试/校验用，不落盘）。"""
        return _diff_snapshots(
            _snapshot_map(prev.dimension_results),
            _snapshot_map(cur.dimension_results),
            cur.competitor.name,
        )

    def update(self, report: CompetitorReport) -> list[TimelineEvent]:
        """对比上次快照，差异记为事件并落盘；随后更新快照。返回本次新增事件。"""
        competitor = report.competitor.name
        bucket = self._bucket(competitor)
        snapshot = _snapshot_map(report.dimension_results)
        events = _diff_snapshots(bucket.get("snapshot", {}), snapshot, competitor)
        if events:
            bucket["events"].extend(asdict(e) for e in events)
        bucket["snapshot"] = snapshot
        bucket["last_analyzed_at"] = report.created_at or now_iso()
        self._save_bucket(competitor, bucket)
        return events

    def last_analyzed_at(self, competitor: str) -> str:
        """上次分析的快照时间（无记录返回空串）。"""
        return str(self._bucket(competitor).get("last_analyzed_at", ""))

    def _bucket(self, competitor: str) -> dict[str, Any]:
        return self._store.get(competitor, {"events": [], "snapshot": {}})

    def _save_bucket(self, competitor: str, bucket: dict[str, Any]) -> None:
        self._store.put(competitor, bucket)
        self._store.save()


def _event_from_dict(data: dict[str, Any]) -> TimelineEvent:
    return TimelineEvent(
        competitor=str(data.get("competitor", "")),
        event_type=str(data.get("event_type", "change")),
        summary=str(data.get("summary", "")),
        occurred_at=str(data.get("occurred_at", "") or now_iso()),
        evidence_urls=list(data.get("evidence_urls", []) or []),
        diff_from=str(data.get("diff_from", "")),
    )


__all__ = ["TimelineEvent", "TimelineMemory"]