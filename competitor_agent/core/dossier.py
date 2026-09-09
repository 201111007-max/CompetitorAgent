"""竞品档案（Dossier）导出（设计文档 82，工单 7）。

单竞品全历史聚合：历史报告索引 + 置信度演进 + 价格/版本/跑分变化曲线 + 证据索引
+ 待跟进问题。**纯聚合零新采集**——只读现有三类存储（reports/timeline/knowledge_base），
不触网、不调 LLM，成本为零随时重放。

与周报的分工（doc 82 §5.2）：周报 = 时间窗内跨竞品变化（新闻）；档案 = 单竞品全历史
（百科）。共用读取层但互不依赖。输出 Markdown + JSON 双份（json 为结构化真源，md 为
渲染，复用 `_write_bytes_atomic` 原子写）。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from competitor_agent.core.checkpoint import _write_bytes_atomic
from competitor_agent.memory.timeline_memory import TimelineMemory
from competitor_agent.observability.logger import get_logger

logger = get_logger("core.dossier")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class DossierReportRef:
    """历史报告索引条目。"""

    created_at: str
    terminal_state: str
    overall_confidence: float
    dimension_count: int
    md_path: str = ""
    json_path: str = ""


@dataclass
class Dossier:
    """单竞品完整档案（结构化真源；Markdown 为渲染形态）。"""

    competitor: str
    generated_at: str = field(default_factory=_now_iso)
    reports: list[DossierReportRef] = field(default_factory=list)
    confidence_trend: list[list[Any]] = field(default_factory=list)  # [(date, confidence)]
    changes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    evidence_index: list[dict[str, Any]] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def total_changes(self) -> int:
        return sum(len(v) for v in self.changes.values())


class DossierBuilder:
    """聚合 reports/timeline/knowledge_base → 单竞品档案。"""

    def __init__(
        self,
        reports_dir: str | Path | None = None,
        data_dir: str | Path | None = None,
        *,
        timeline: TimelineMemory | None = None,
        store: Any = None,
    ) -> None:
        self._reports_dir = self._resolve_reports_dir(reports_dir)
        self._data_dir = Path(data_dir).expanduser() if data_dir else None
        self._timeline = timeline or (
            TimelineMemory(data_dir=self._data_dir) if self._data_dir else TimelineMemory()
        )
        self._store = store

    @staticmethod
    def _resolve_reports_dir(reports_dir: str | Path | None) -> Path:
        if reports_dir:
            return Path(reports_dir).expanduser()
        from competitor_agent.core.report_archiver import resolve_output_dir

        return resolve_output_dir(None)

    # ── 读取 ──────────────────────────────────────────────────

    def _load_reports(self, competitor: str) -> list[dict[str, Any]]:
        """<reports_dir>/*.json 中该竞品的全部归档（按 created_at 升序）。"""
        if not self._reports_dir.is_dir():
            return []
        rows: list[tuple[str, str, dict[str, Any]]] = []  # (created_at, path, data)
        for path in sorted(self._reports_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(data, dict):
                continue
            name = self._competitor_name(data)
            if name != competitor:
                continue
            rows.append((str(data.get("created_at") or ""), str(path), data))
        rows.sort(key=lambda r: r[0])
        return [data for _c, _p, data in rows]

    @staticmethod
    def _competitor_name(data: dict[str, Any]) -> str:
        """归档 JSON 的竞品名（兼容 str 与 {"name": …} 两种形态）。"""
        raw = data.get("competitor")
        if isinstance(raw, dict):
            return str(raw.get("name") or "").strip()
        return str(raw or "").strip()

    def _load_events(self, competitor: str, window_days: int | None) -> list[dict[str, Any]]:
        """该竞品时间线事件（occurred_at 升序；window_days 有界时只保留窗口内）。"""
        try:
            events = self._timeline.events(competitor, limit=500)
        except Exception:  # noqa: BLE001 — 时间线读取失败不炸档案
            logger.warning("时间线读取失败（竞品: %s）", competitor, exc_info=True)
            events = []
        rows: list[dict[str, Any]] = [
            {
                "event_type": str(getattr(e, "event_type", "") or ""),
                "summary": str(getattr(e, "summary", "") or ""),
                "occurred_at": str(getattr(e, "occurred_at", "") or ""),
                "diff_from": str(getattr(e, "diff_from", "") or ""),
                "evidence_urls": [str(u) for u in (getattr(e, "evidence_urls", None) or [])],
            }
            for e in events
        ]
        if window_days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
            rows = [r for r in rows if r["occurred_at"] >= cutoff]
        rows.sort(key=lambda r: r["occurred_at"])
        return rows

    def _build_evidence_index(self, competitor: str) -> list[dict[str, Any]]:
        """知识库 chunk 聚合 → 去重证据来源索引（source_url → 维度/首见）。"""
        if self._store is None:
            return []
        try:
            chunks = self._store.by_competitor(competitor)
        except Exception:
            logger.warning("知识库读取失败（竞品: %s）", competitor, exc_info=True)
            return []
        index: dict[str, dict[str, Any]] = {}
        for chunk in chunks:
            url = str(getattr(chunk, "source_url", "") or "")
            if not url.startswith("http"):
                continue
            dimension = str(getattr(chunk, "dimension", "") or "")
            entry = index.setdefault(
                url, {"source_url": url, "dimensions": [], "first_seen": _now_iso()[:10]}
            )
            if dimension and dimension not in entry["dimensions"]:
                entry["dimensions"].append(dimension)
        rows = sorted(index.values(), key=lambda e: e["source_url"])
        for row in rows:
            row["dimensions"] = ", ".join(row["dimensions"])
        return rows

    # ── 聚合 ──────────────────────────────────────────────────

    def build(self, competitor: str, *, window_days: int | None = None) -> Dossier:
        """构建单竞品档案（window_days=None = 全历史）。"""
        competitor = str(competitor or "").strip()
        reports_data = self._load_reports(competitor)
        reports = [
            DossierReportRef(
                created_at=str(d.get("created_at") or ""),
                terminal_state=str(d.get("terminal_state") or ""),
                overall_confidence=float(d.get("overall_confidence") or 0.0),
                dimension_count=int(
                    d.get("dimension_count") or len(d.get("dimensions") or [])
                ),
                md_path=str(d.get("markdown_path") or ""),
                json_path="",
            )
            for d in reports_data
        ]
        trend = [
            [str(d.get("created_at") or "")[:10], float(d.get("overall_confidence") or 0.0)]
            for d in reports_data
            if d.get("created_at")
        ]
        events = self._load_events(competitor, window_days)
        changes: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            changes.setdefault(event["event_type"] or "change", []).append(event)
        questions: list[str] = []
        for data in reversed(reports_data):  # 旧 → 新，新报告的同名缺口排后（去重保先见）
            gaps = data.get("gaps_pending") or data.get("pending_gaps") or []
            for gap in gaps:
                gap_text = str(gap)
                if gap_text and gap_text not in questions:
                    questions.append(gap_text)
        return Dossier(
            competitor=competitor,
            reports=reports,
            confidence_trend=trend,
            changes=changes,
            evidence_index=self._build_evidence_index(competitor),
            open_questions=questions,
        )

    # ── 渲染 ──────────────────────────────────────────────────

    def render_markdown(self, dossier: Dossier) -> str:
        """对外发布形态（doc 82 §2.2 七节结构）。"""
        today = dossier.generated_at[:10]
        lines: list[str] = [
            f"# {dossier.competitor} 档案（截至 {today}）",
            "",
            (
                f"> 覆盖 {len(dossier.reports)} 份历史报告 / {dossier.total_changes} 条变化事件"
                f" · 证据来源 {len(dossier.evidence_index)} 条"
            ),
        ]
        if dossier.reports:
            window = f"[{dossier.reports[0].created_at[:10]} ~ {today}]"
            lines[2] += f" · 数据窗口 {window}"
        lines.append("")

        lines.append("## 1. 置信度演进")
        lines.append("")
        if dossier.confidence_trend:
            lines.append("| 日期 | 综合置信度 |")
            lines.append("|------|-----------|")
            for date, conf in dossier.confidence_trend:
                bar = "█" * round(float(conf) * 10)
                lines.append(f"| {date} | {float(conf):.2f} {bar} |")
        else:
            lines.append("_暂无历史报告。_")
        lines.append("")

        section_no = 2
        for event_type, label in (
            ("price_change", "价格变化"),
            ("score_change", "跑分变化"),
            ("version_release", "版本发布"),
            ("feature_added", "功能新增"),
        ):
            if event_type not in dossier.changes:
                continue
            events = dossier.changes[event_type]
            lines.append(f"## {section_no}. {label}")
            lines.append("")
            for e in events:
                date = e["occurred_at"][:10] or "-"
                diff = f"（{e['diff_from']} → {date}）" if e["diff_from"] else ""
                lines.append(f"- [{date}] {e['summary']}{diff}")
                for url in e["evidence_urls"][:2]:
                    lines.append(f"  - 来源: {url}")
            lines.append("")
            section_no += 1
        if section_no == 2:
            lines.append("## 2. 变化事件")
            lines.append("")
            lines.append("_暂无变化事件。_")
            lines.append("")
            section_no = 3

        lines.append(f"## {section_no}. 历史报告索引")
        lines.append("")
        if dossier.reports:
            lines.append("| 日期 | 终态 | 置信度 | 维度数 |")
            lines.append("|------|------|--------|--------|")
            for r in dossier.reports:
                lines.append(
                    f"| {r.created_at[:10]} | {r.terminal_state} | {r.overall_confidence:.2f} | {r.dimension_count} |"
                )
        else:
            lines.append("_暂无历史报告。_")
        lines.append("")

        section_no += 1
        lines.append(f"## {section_no}. 证据来源索引")
        lines.append("")
        if dossier.evidence_index:
            lines.append("| 来源 | 维度 | 首见 |")
            lines.append("|------|------|------|")
            for e in dossier.evidence_index:
                lines.append(f"| {e['source_url']} | {e['dimensions'] or '-'} | {e['first_seen']} |")
        else:
            lines.append("_暂无知识库证据。_")
        lines.append("")

        section_no += 1
        lines.append(f"## {section_no}. 待跟进问题")
        lines.append("")
        if dossier.open_questions:
            for q in dossier.open_questions:
                lines.append(f"- {q}")
        else:
            lines.append("_无待跟进问题。_")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("_本档案由 competitor_agent 聚合生成（纯本地读取，零新采集）。_")
        return "\n".join(lines)

    # ── 落盘 ──────────────────────────────────────────────────

    def write(self, dossier: Dossier) -> tuple[Path, Path]:
        """<reports>/dossiers/<competitor>.md + .json（原子写；json 为结构化真源）。"""
        from competitor_agent.core.report_archiver import _safe_filename

        out_dir = self._reports_dir / "dossiers"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = _safe_filename(dossier.competitor)
        json_path = out_dir / f"{safe}.json"
        md_path = out_dir / f"{safe}.md"
        payload = json.dumps(dossier.to_dict(), ensure_ascii=False, indent=2)
        _write_bytes_atomic(json_path, payload.encode("utf-8"))
        _write_bytes_atomic(md_path, self.render_markdown(dossier).encode("utf-8"))
        logger.info("竞品档案已导出: %s / %s", md_path, json_path)
        return md_path, json_path


__all__ = [
    "Dossier",
    "DossierBuilder",
    "DossierReportRef",
]
