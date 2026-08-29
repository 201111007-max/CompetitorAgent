"""周报聚合（设计文档 67 §2.3.2）— 跨竞品「本周变化」时间序列叙事

读取 ``<data_dir>/reports/competitor/*.json`` + ``TimelineMemory``（
``<data_dir>/memory/timeline.json``）聚合近 N 天（``schedule.weekly_window_days``，
缺省 7）的跨竞品变化：价格变动 / 版本功能发布 / 榜单分数变化 / 新增竞品 /
各竞品整体置信度对比表。输出 ``<data_dir>/reports/weekly/<YYYY-Www>.md + .json``。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from competitor_agent.config.loader import load_config
from competitor_agent.core.checkpoint import _write_bytes_atomic
from competitor_agent.secret_vault import get_data_dir

logger = logging.getLogger("competitor_agent.core.weekly_report")

# 时间线事件类型 → 周报章节
_EVENT_SECTION = {
    "price_change": "价格变动",
    "score_change": "榜单分数变化",
    "version_release": "版本/功能发布",
    "feature_added": "版本/功能发布",
}


def _iso_short(value: str) -> str:
    return str(value or "")[:10]


def _in_window(value: str, window_start: datetime, now: datetime) -> bool:
    """ISO 时间戳是否落在 [window_start, now] 窗口内（解析失败按不在窗口处理）。"""
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    return window_start <= ts <= now


class WeeklyReportBuilder:
    """跨竞品周报聚合器（纯本地读取 + 聚合，不触网络）。"""

    def __init__(
        self,
        *,
        reports_dir: str | Path | None = None,
        data_dir: str | Path | None = None,
        window_days: int = 7,
        output_dir: str | Path | None = None,
    ) -> None:
        self._reports_dir = Path(reports_dir).expanduser() if reports_dir else self._default_reports_dir()
        self._data_dir = Path(data_dir).expanduser() if data_dir else get_data_dir()
        self._window_days = max(1, int(window_days))
        # 周报默认落在 reports 根下 weekly/（与竞品/对比报告同根）
        self._output_dir = (
            Path(output_dir).expanduser()
            if output_dir
            else self._reports_dir.parent / "weekly"
        )

    @staticmethod
    def _default_reports_dir() -> Path:
        cfg = load_config().report
        path = Path(cfg.output_dir).expanduser()
        return path if path.is_absolute() else Path.cwd() / path

    # ── 读取 ──────────────────────────────────────────────────

    def _load_report_dicts(self) -> list[dict[str, Any]]:
        """读取 <reports_dir>/*.json（report_to_dict 产物），按竞品取最新一份。"""
        if not self._reports_dir.is_dir():
            return []
        latest: dict[str, dict[str, Any]] = {}
        for path in sorted(self._reports_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("周报跳过损坏 JSON: %s", path)
                continue
            if not isinstance(data, dict):
                continue
            name = str(data.get("competitor") or "").strip()
            if not name:
                continue
            created = str(data.get("created_at") or "")
            # 同竞品取最新（created_at 字典序即时间序）
            if name not in latest or created > str(latest[name].get("created_at") or ""):
                latest[name] = data
        return list(latest.values())

    def _load_timeline_events(self) -> list[dict[str, Any]]:
        """读取 <data_dir>/memory/timeline.json 全部事件（JsonStore 结构兼容）。"""
        from competitor_agent.memory.json_store import JsonStore

        store = JsonStore("timeline", self._data_dir)
        events: list[dict[str, Any]] = []
        for bucket in store.all().values():
            if not isinstance(bucket, dict):
                continue
            for e in bucket.get("events") or []:
                if isinstance(e, dict):
                    events.append(e)
        return events

    # ── 聚合 ──────────────────────────────────────────────────

    def build(self, now: datetime | None = None) -> dict[str, Any]:
        """聚合近 N 天跨竞品变化 → 结构化周报数据。"""
        now = now or datetime.now(timezone.utc)
        window_start = now - timedelta(days=self._window_days)
        reports = self._load_report_dicts()
        events = self._load_timeline_events()

        in_window_reports = [
            r for r in reports if _in_window(str(r.get("created_at") or ""), window_start, now)
        ]
        in_window_events = [
            e for e in events if _in_window(str(e.get("occurred_at") or ""), window_start, now)
        ]

        # 各变化分类
        by_kind: dict[str, list[dict[str, Any]]] = {}
        for e in in_window_events:
            kind = str(e.get("event_type") or "")
            by_kind.setdefault(kind, []).append(e)

        # 新增竞品：窗口内出现且窗口前无更早报告
        earlier_names = {
            str(r.get("competitor") or "")
            for r in reports
            if not _in_window(str(r.get("created_at") or ""), window_start, now)
        }
        new_competitors = [
            {
                "name": str(r.get("competitor") or ""),
                "created_at": str(r.get("created_at") or ""),
                "overall_confidence": round(float(r.get("overall_confidence") or 0.0), 3),
            }
            for r in in_window_reports
            if str(r.get("competitor") or "") not in earlier_names
        ]

        # 各竞品整体置信度对比表（窗口内最新）
        confidence_rows: list[dict[str, Any]] = [
            {
                "competitor": str(r.get("competitor") or ""),
                "overall_confidence": round(float(r.get("overall_confidence") or 0.0), 3),
                "terminal_state": str(r.get("terminal_state") or ""),
                "created_at": str(r.get("created_at") or "")[:10],
                "status": str(r.get("status") or "approved"),
            }
            for r in in_window_reports
        ]
        confidence_rows.sort(key=lambda x: x["overall_confidence"], reverse=True)

        # high-impact：价格变动 / 榜单变化 / 新增竞品（周报审批门触发项）
        high_impact = bool(
            by_kind.get("price_change")
            or by_kind.get("score_change")
            or new_competitors
        )

        return {
            "week_label": self.week_label(now),
            "window_start": window_start.isoformat(),
            "window_end": now.isoformat(),
            "window_days": self._window_days,
            "created_at": now.isoformat(),
            "high_impact": high_impact,
            "price_changes": [
                self._event_row(e, "price") for e in by_kind.get("price_change", [])
            ],
            "score_changes": [
                self._event_row(e, "score") for e in by_kind.get("score_change", [])
            ],
            "releases": [
                self._event_row(e, "release")
                for e in by_kind.get("version_release", [])
                + by_kind.get("feature_added", [])
            ],
            "new_competitors": new_competitors,
            "confidence": confidence_rows,
        }

    @staticmethod
    def week_label(now: datetime) -> str:
        """ISO 周标签 `<YYYY>-W<ww>`（与文件命名一致）。"""
        year, week, _ = now.isocalendar()
        return f"{year}-W{week:02d}"

    @staticmethod
    def _event_row(event: dict[str, Any], _kind: str) -> dict[str, Any]:
        return {
            "competitor": str(event.get("competitor") or ""),
            "summary": str(event.get("summary") or ""),
            "occurred_at": str(event.get("occurred_at") or ""),
            "diff_from": str(event.get("diff_from") or ""),
            "evidence_urls": [str(u) for u in (event.get("evidence_urls") or [])],
        }

    # ── 渲染 / 落盘 ───────────────────────────────────────────

    def render_markdown(self, data: dict[str, Any]) -> str:
        """周报数据 → Markdown 正文。"""
        lines = [
            f"# 竞品周报 {data['week_label']}",
            "",
            (
                f"> 窗口：{_iso_short(data['window_start'])} ~ {_iso_short(data['window_end'])} "
                f"（{data['window_days']} 天） | 生成于 {_iso_short(data['created_at'])}"
            ),
            "",
        ]
        sections = [
            ("## 本周价格变动", data["price_changes"], "无价格变动"),
            ("## 榜单分数变化", data["score_changes"], "无榜单分数变化"),
            ("## 版本/功能发布", data["releases"], "无版本/功能发布"),
            ("## 新增竞品", data["new_competitors"], "无新增竞品"),
        ]
        for title, rows, empty in sections:
            lines.append(title)
            lines.append("")
            if not rows:
                lines.append(empty)
            else:
                for row in rows:
                    comp = row.get("competitor") or row.get("name") or ""
                    summary = str(row.get("summary") or "")
                    date = _iso_short(str(row.get("occurred_at") or row.get("created_at") or ""))
                    lines.append(f"- [{date}] **{comp}**{': ' + summary if summary else ''}")
            lines.append("")

        lines.append("## 各竞品整体置信度")
        lines.append("")
        rows = data["confidence"]
        if not rows:
            lines.append("（本周无竞品报告数据）")
        else:
            lines.append("| 竞品 | 置信度 | 终态 | 生成日期 | 状态 |")
            lines.append("|------|-------|------|---------|------|")
            for r in rows:
                lines.append(
                    f"| {r['competitor']} | {r['overall_confidence']:.3f} | "
                    f"{r['terminal_state']} | {r['created_at']} | {r['status']} |"
                )
            lines.append("")
        if data["high_impact"]:
            lines.append("> ⚠ 本周含 high-impact 变化（价格/榜单/新增竞品），建议人工复核。")
            lines.append("")
        return "\n".join(lines)

    def write(self, data: dict[str, Any], now: datetime | None = None) -> tuple[Path, Path]:
        """原子写 <output_dir>/<YYYY-Www>.md + .json，返回 (md_path, json_path)。"""
        now = now or datetime.now(timezone.utc)
        label = self.week_label(now)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        md_path = self._output_dir / f"{label}.md"
        json_path = self._output_dir / f"{label}.json"
        _write_bytes_atomic(md_path, self.render_markdown(data).encode("utf-8"))
        _write_bytes_atomic(
            json_path,
            json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        logger.info("周报已生成: %s / %s", md_path, json_path)
        return md_path, json_path


__all__ = ["WeeklyReportBuilder"]
