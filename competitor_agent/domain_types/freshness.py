"""新鲜度元数据（设计文档 26 §3.1）

每次分析产出 ``ReportFreshness``：``collected_at``、各维度 ``age_days``、
数据源抓取时间。超过维度 TTL 时报告标 ``⚠️ 数据可能过期`` 并提示 re-analyze。
供 ``refresh_stale()`` 判定过期竞品与 ``MarkdownRenderer`` 渲染注记。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# 维度 → TTL（天）：超过视为"数据可能过期"（config.freshness 可覆盖）
DEFAULT_TTL_DAYS: dict[str, int] = {
    "pricing": 7,
    "performance": 14,
    "feature": 30,
    "ecosystem": 30,
    "sentiment": 7,
    "roadmap": 14,
}


def _parse_iso_dt(value: str) -> datetime | None:
    """把 ISO 时间戳解析为 aware datetime；失败返回 None"""
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _latest_fetch(result: object) -> datetime | None:
    """维度结果中最近的证据抓取时间（evidence.access_time / Ball retrieved_at）。"""
    latest: datetime | None = None
    for ev in getattr(result, "evidence", None) or []:
        ts = getattr(ev, "access_time", "") or getattr(ev, "retrieved_at", "")
        dt = _parse_iso_dt(str(ts))
        if dt is not None and (latest is None or dt > latest):
            latest = dt
    return latest


@dataclass
class ReportFreshness:
    """单次报告的新鲜度元数据

    - ``dimension_ages``: dimension → 距最近抓取的天数（无证据/无时间则不给该维度）
    - ``source_retrieved_at``: source_name → 抓取时间（ISO）
    - ``stale_dimensions``: age 超过维度 TTL 的维度列表
    """

    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    dimension_ages: dict[str, float] = field(default_factory=dict)
    source_retrieved_at: dict[str, str] = field(default_factory=dict)
    stale_dimensions: list[str] = field(default_factory=list)

    @classmethod
    def from_results(
        cls,
        results: Sequence[object],
        ttl_days: dict[str, int] | None = None,
        now: datetime | None = None,
    ) -> ReportFreshness:
        """汇总维度结果生成新鲜度。

        ``results`` 元素 duck-type 出 ``dimension`` / ``timestamp`` / ``evidence``
        （含 ``access_time``），避免 domain 与 memory 之间循环依赖。
        """
        ttl = dict(DEFAULT_TTL_DAYS)
        if ttl_days:
            ttl.update(ttl_days)
        now_dt = now or datetime.now(timezone.utc)

        ages: dict[str, float] = {}
        retrieved: dict[str, str] = {}
        for r in results:
            dim = str(getattr(r, "dimension", ""))
            if not dim:
                continue
            latest = _latest_fetch(r)
            if latest is None:
                # 无证据抓取时间：不给该维度年龄（无法判定新鲜度）
                continue
            age = max(0.0, (now_dt - latest).total_seconds() / 86400.0)
            ages[dim] = round(age, 2)
            ts = str(getattr(r, "timestamp", "") or latest.isoformat())
            retrieved[dim] = ts

        stale = sorted(d for d, age in ages.items() if age > float(ttl.get(d, DEFAULT_TTL_DAYS.get(d, 30))))
        return cls(
            analyzed_at=now_dt.isoformat(),
            dimension_ages=ages,
            source_retrieved_at=retrieved,
            stale_dimensions=stale,
        )

    def markdown_note(self) -> str:
        """渲染新鲜度注记：超出 TTL 的维度提示 re-analyze。"""
        lines: list[str] = [f"> 数据新鲜度: 分析于 {self.analyzed_at}"]
        if self.stale_dimensions:
            parts = ", ".join(f"`{d}`={self.dimension_ages.get(d, 0)}d" for d in self.stale_dimensions)
            lines.append(f"> ⚠️ **数据可能过期**（超过 TTL）: {parts}")
            lines.append("> 建议执行 `re-analyze` 重新爬取。")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyzed_at": self.analyzed_at,
            "dimension_ages": self.dimension_ages,
            "source_retrieved_at": self.source_retrieved_at,
            "stale_dimensions": self.stale_dimensions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ReportFreshness | None:
        if not data:
            return None
        return cls(
            analyzed_at=str(data.get("analyzed_at", "")),
            dimension_ages=dict(data.get("dimension_ages", {}) or {}),
            source_retrieved_at=dict(data.get("source_retrieved_at", {}) or {}),
            stale_dimensions=list(data.get("stale_dimensions", []) or []),
        )


def stale_under_ttl(
    session_raw: dict[str, Any],
    ttl_days: dict[str, int] | None = None,
    now: datetime | None = None,
) -> list[str]:
    """按维度 TTL 判定归档会话的过期维度（设计文档 26 §3.3 的判定依据）。

    - 归档含 ``freshness`` 元数据：用其 ``dimension_ages`` 对（可能被覆盖的）当前 TTL 重算；
    - 否则回退到 ``created_at`` 整体年龄：超过最小 TTL 视为全部维度过期。
    """
    ttl = dict(DEFAULT_TTL_DAYS)
    if ttl_days:
        ttl.update(ttl_days)

    fresh = ReportFreshness.from_dict(session_raw.get("freshness"))
    if fresh is not None and fresh.dimension_ages:
        return sorted(
            d
            for d, age in fresh.dimension_ages.items()
            if age > float(ttl.get(d, DEFAULT_TTL_DAYS.get(d, 30)))
        )

    created = str(session_raw.get("created_at") or "")
    dt = _parse_iso_dt(created)
    if dt is None:
        return []
    now_dt = now or datetime.now(timezone.utc)
    age = (now_dt - dt).total_seconds() / 86400.0
    min_ttl = min(ttl.values(), default=30)
    return sorted(ttl) if age > min_ttl else []


__all__ = ["DEFAULT_TTL_DAYS", "ReportFreshness", "stale_under_ttl"]