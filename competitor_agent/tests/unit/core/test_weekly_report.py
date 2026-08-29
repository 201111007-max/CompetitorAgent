"""设计文档 67 §2.3.2 — 周报聚合单测。

从 reports/*.json + timeline.json + 时间窗聚合出周报（价格/版本/榜单/新增竞品/置信表）、
时间窗过滤、无数据空周报、markdown+json 双产物字段、high-impact 标记。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from competitor_agent.core.weekly_report import WeeklyReportBuilder

_NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)


def _iso(days_ago: int = 0) -> str:
    return (_NOW - timedelta(days=days_ago)).isoformat()


def _report_dict(name: str, confidence: float, days_ago: int = 1, status: str = "approved") -> dict:
    return {
        "schema_version": "1.0.0",
        "competitor": name,
        "terminal_state": "success",
        "overall_confidence": confidence,
        "created_at": _iso(days_ago),
        "dimensions": [{"field": "pricing", "status": "COMPLETE", "confidence": confidence, "summary": "", "evidence": []}],
        "status": status,
    }


def _timeline_bucket(events: list[dict]) -> dict:
    return {"events": events, "snapshot": {}, "last_analyzed_at": _iso(0)}


def _write_timeline(data_dir: Path, buckets: dict[str, dict]) -> None:
    mem = data_dir / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    (mem / "timeline.json").write_text(json.dumps(buckets, ensure_ascii=False), encoding="utf-8")


def _event(competitor: str, kind: str, summary: str, days_ago: int = 1) -> dict:
    return {
        "competitor": competitor,
        "event_type": kind,
        "summary": summary,
        "occurred_at": _iso(days_ago),
        "evidence_urls": ["https://x.test/"],
        "diff_from": _iso(days_ago + 3),
    }


def _builder(tmp_path: Path) -> WeeklyReportBuilder:
    return WeeklyReportBuilder(
        reports_dir=tmp_path / "reports",
        data_dir=tmp_path,
        window_days=7,
        output_dir=tmp_path / "weekly",
    )


class TestWeeklyAggregation:
    def test_aggregates_sections(self, tmp_path: Path) -> None:
        reports = tmp_path / "reports"
        reports.mkdir(parents=True)
        (reports / "cursor.json").write_text(
            json.dumps(_report_dict("cursor", 0.8), ensure_ascii=False), encoding="utf-8"
        )
        (reports / "windsurf.json").write_text(
            json.dumps(_report_dict("windsurf", 0.6, days_ago=2), ensure_ascii=False),
            encoding="utf-8",
        )
        _write_timeline(
            tmp_path,
            {
                "cursor": _timeline_bucket(
                    [
                        _event("cursor", "price_change", "价格变化: $20 → $40"),
                        _event("cursor", "score_change", "SWE-bench 45.2 → 48.1"),
                        _event("cursor", "version_release", "v1.5 发布"),
                    ]
                )
            },
        )
        data = _builder(tmp_path).build(_NOW)
        assert data["week_label"] == "2026-W35" or data["week_label"].startswith("2026-W")
        assert len(data["price_changes"]) == 1
        assert len(data["score_changes"]) == 1
        assert len(data["releases"]) == 1
        assert data["price_changes"][0]["competitor"] == "cursor"
        # 置信度对比表：窗口内最新报告
        assert {r["competitor"] for r in data["confidence"]} == {"cursor", "windsurf"}
        assert data["confidence"][0]["overall_confidence"] == 0.8
        # high-impact：价格/榜单/新增竞品任一
        assert data["high_impact"] is True

    def test_window_filters_old_events(self, tmp_path: Path) -> None:
        reports = tmp_path / "reports"
        reports.mkdir(parents=True)
        # 报告与事件都在窗口外（30 天前）→ 不聚合
        (reports / "cursor.json").write_text(
            json.dumps(_report_dict("cursor", 0.8, days_ago=30), ensure_ascii=False), encoding="utf-8"
        )
        _write_timeline(
            tmp_path,
            {"cursor": _timeline_bucket([_event("cursor", "price_change", "old", days_ago=30)])},
        )
        data = _builder(tmp_path).build(_NOW)
        assert data["price_changes"] == []
        assert data["confidence"] == []
        assert data["high_impact"] is False

    def test_new_competitor_detected(self, tmp_path: Path) -> None:
        reports = tmp_path / "reports"
        reports.mkdir(parents=True)
        # cursor 有窗口前的老报告；windsurf 仅窗口内（新增）
        (reports / "cursor.json").write_text(
            json.dumps(_report_dict("cursor", 0.8, days_ago=30), ensure_ascii=False), encoding="utf-8"
        )
        (reports / "windsurf.json").write_text(
            json.dumps(_report_dict("windsurf", 0.6, days_ago=1), ensure_ascii=False), encoding="utf-8"
        )
        data = _builder(tmp_path).build(_NOW)
        assert data["new_competitors"] == [{"name": "windsurf", "created_at": _iso(1), "overall_confidence": 0.6}]
        assert data["high_impact"] is True

    def test_empty_yields_empty_weekly(self, tmp_path: Path) -> None:
        data = _builder(tmp_path).build(_NOW)
        assert data["confidence"] == []
        assert data["price_changes"] == []
        assert data["high_impact"] is False


class TestWeeklyWrite:
    def test_writes_md_and_json(self, tmp_path: Path) -> None:
        reports = tmp_path / "reports"
        reports.mkdir(parents=True)
        (reports / "cursor.json").write_text(
            json.dumps(_report_dict("cursor", 0.8), ensure_ascii=False), encoding="utf-8"
        )
        builder = _builder(tmp_path)
        data = builder.build(_NOW)
        md_path, json_path = builder.write(data, _NOW)
        assert md_path.exists() and json_path.exists()
        assert md_path.suffix == ".md" and json_path.suffix == ".json"
        assert md_path.name.startswith("2026-W")
        md = md_path.read_text(encoding="utf-8")
        assert "竞品周报" in md
        assert "cursor" in md
        assert "各竞品整体置信度" in md
        saved = json.loads(json_path.read_text(encoding="utf-8"))
        assert saved["week_label"] == data["week_label"]
        assert "high_impact" in saved
