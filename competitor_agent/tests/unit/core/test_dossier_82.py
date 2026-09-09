"""设计文档 82：竞品档案（Dossier）导出——纯聚合零新采集。

3 份报告 + 5 条时间线事件 → 档案各节计数/排序正确；空态不编造；json 与 md 一致
（json 为结构化真源）；原子写；CLI 入口解析。
"""

from __future__ import annotations

import json
from pathlib import Path

from competitor_agent.core.dossier import DossierBuilder, DossierReportRef
from competitor_agent.memory.timeline_memory import TimelineEvent, TimelineMemory


def _report_dict(name: str, created_at: str, confidence: float, gaps: list[str] | None = None) -> dict:
    return {
        "schema_version": "0.13.0",
        "competitor": name,
        "terminal_state": "success",
        "overall_confidence": confidence,
        "created_at": created_at,
        "dimensions": [{"dimension": "pricing", "summary": "s", "details": {}, "confidence": confidence}],
        "gaps_pending": gaps or [],
    }


def _seed(tmp_path: Path, events: list[TimelineEvent]) -> TimelineMemory:
    timeline = TimelineMemory(data_dir=tmp_path)
    for e in events:
        timeline.append(e)
    return timeline


class TestBuild:
    def test_aggregates_reports_events_trend_questions(self, tmp_path: Path) -> None:
        reports = tmp_path / "competitor"
        reports.mkdir()
        for i, (ts, conf, gaps) in enumerate(
            [
                ("2026-09-01T00:00:00+00:00", 0.5, ["价格待核验"]),
                ("2026-09-05T00:00:00+00:00", 0.7, []),
                ("2026-09-08T00:00:00+00:00", 0.8, ["价格待核验", "版本待跟进"]),
            ]
        ):
            (reports / f"cursor_{i}.json").write_text(
                json.dumps(_report_dict("cursor", ts, conf, gaps), ensure_ascii=False), encoding="utf-8"
            )
        timeline = _seed(
            tmp_path,
            [
                TimelineEvent(competitor="cursor", event_type="price_change", summary="价格变化: $10 → $20",
                              occurred_at="2026-09-06T00:00:00+00:00", evidence_urls=["https://x"]),
                TimelineEvent(competitor="cursor", event_type="score_change", summary="跑分 50 → 55 [口径: 第三方实测]",
                              occurred_at="2026-09-07T00:00:00+00:00"),
                TimelineEvent(competitor="cursor", event_type="version_release", summary="发布 2.0",
                              occurred_at="2026-09-03T00:00:00+00:00"),
                TimelineEvent(competitor="cursor", event_type="feature_added", summary="新增后台代理",
                              occurred_at="2026-09-04T00:00:00+00:00"),
                TimelineEvent(competitor="cursor", event_type="score_change", summary="跑分 55 → 60",
                              occurred_at="2026-09-09T00:00:00+00:00"),
                TimelineEvent(competitor="other", event_type="price_change", summary="别家的事件",
                              occurred_at="2026-09-06T00:00:00+00:00"),
            ],
        )
        builder = DossierBuilder(reports_dir=reports, data_dir=tmp_path, timeline=timeline)
        dossier = builder.build("cursor")

        assert len(dossier.reports) == 3  # 只聚合该竞品
        assert [r.overall_confidence for r in dossier.reports] == [0.5, 0.7, 0.8]  # 时间升序
        assert [d for d, _ in dossier.confidence_trend] == ["2026-09-01", "2026-09-05", "2026-09-08"]
        assert dossier.total_changes == 5
        assert len(dossier.changes["score_change"]) == 2  # 时间升序
        assert dossier.changes["score_change"][0]["occurred_at"] < dossier.changes["score_change"][1]["occurred_at"]
        assert dossier.open_questions == ["价格待核验", "版本待跟进"]  # 并集去重

    def test_window_days_filters_events(self, tmp_path: Path) -> None:
        timeline = _seed(
            tmp_path,
            [
                TimelineEvent(competitor="cursor", event_type="price_change", summary="旧事件",
                              occurred_at="2020-01-01T00:00:00+00:00"),
                TimelineEvent(competitor="cursor", event_type="price_change", summary="新事件",
                              occurred_at="2099-01-01T00:00:00+00:00"),
            ],
        )
        builder = DossierBuilder(reports_dir=tmp_path / "nope", data_dir=tmp_path, timeline=timeline)
        dossier = builder.build("cursor", window_days=30)
        assert [e["summary"] for e in dossier.changes["price_change"]] == ["新事件"]

    def test_store_evidence_index(self, tmp_path: Path) -> None:
        class _FakeStore:
            def by_competitor(self, competitor: str) -> list:
                return [
                    SimpleNamespace(source_url="https://a", dimension="pricing"),
                    SimpleNamespace(source_url="https://a", dimension="performance"),
                    SimpleNamespace(source_url="", dimension="pricing"),  # 无 URL 不入索引
                ]

        from types import SimpleNamespace

        builder = DossierBuilder(
            reports_dir=tmp_path / "nope", data_dir=tmp_path, store=_FakeStore()
        )
        dossier = builder.build("cursor")
        assert len(dossier.evidence_index) == 1
        assert dossier.evidence_index[0]["dimensions"] == "pricing, performance"


class TestRenderAndWrite:
    def _builder(self, tmp_path: Path) -> tuple[DossierBuilder, Path]:
        reports = tmp_path / "competitor"
        reports.mkdir()
        (reports / "cursor.json").write_text(
            json.dumps(_report_dict("cursor", "2026-09-08T00:00:00+00:00", 0.8, ["价格待核验"]),
                       ensure_ascii=False),
            encoding="utf-8",
        )
        timeline = _seed(
            tmp_path,
            [TimelineEvent(competitor="cursor", event_type="price_change", summary="价格变化: $10 → $20",
                           occurred_at="2026-09-08T00:00:00+00:00", evidence_urls=["https://x"])],
        )
        return DossierBuilder(reports_dir=reports, data_dir=tmp_path, timeline=timeline), reports

    def test_markdown_sections_and_write(self, tmp_path: Path) -> None:
        builder, reports = self._builder(tmp_path)
        dossier = builder.build("cursor")
        md = builder.render_markdown(dossier)
        assert "# cursor 档案（截至" in md
        assert "## 1. 置信度演进" in md
        assert "## 2. 价格变化" in md and "$10 → $20" in md
        assert "## 3. 历史报告索引" in md
        assert "## 4. 证据来源索引" in md
        assert "## 5. 待跟进问题" in md and "价格待核验" in md
        md_path, json_path = builder.write(dossier)
        assert md_path == reports / "dossiers" / "cursor.md"
        assert json_path == reports / "dossiers" / "cursor.json"
        # json 为结构化真源，md 为渲染——数据一致
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["competitor"] == "cursor"
        assert data["reports"][0]["overall_confidence"] == 0.8
        assert "0.80" in md

    def test_empty_state_valid_no_fabrication(self, tmp_path: Path) -> None:
        """doc 82 §3.2：无报告无事件 → 合法空态档案（不崩、不编造）。"""
        builder = DossierBuilder(reports_dir=tmp_path / "nope", data_dir=tmp_path)
        dossier = builder.build("ghost")
        assert dossier.reports == []
        assert dossier.total_changes == 0
        md = builder.render_markdown(dossier)
        assert "暂无" in md
        md_path, json_path = builder.write(dossier)
        assert json.loads(json_path.read_text(encoding="utf-8"))["competitor"] == "ghost"
        assert "暂无历史报告" in md_path.read_text(encoding="utf-8")

    def test_report_ref_defaults(self) -> None:
        ref = DossierReportRef(created_at="2026-09-08", terminal_state="success",
                               overall_confidence=0.5, dimension_count=3)
        assert ref.md_path == ""


class TestCliEntry:
    def test_parser(self) -> None:
        from competitor_agent.cli import build_parser

        args = build_parser().parse_args(["dossier", "--competitor", "cursor", "--window-days", "90"])
        assert args.competitor == "cursor"
        assert args.window_days == 90

    def test_run_dossier_smoke(self, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
        """CLI 入口纯本地聚合（无 API/LLM 构造）。"""
        from competitor_agent.cli import _run_dossier

        reports = tmp_path / "competitor"
        reports.mkdir()
        (reports / "cursor.json").write_text(
            json.dumps(_report_dict("cursor", "2026-09-08T00:00:00+00:00", 0.8), ensure_ascii=False),
            encoding="utf-8",
        )
        import argparse

        args = argparse.Namespace(
            competitor="cursor", window_days=None, reports_dir=str(reports), data_dir=str(tmp_path)
        )
        code = _run_dossier(args)
        assert code == 0
        assert (reports / "dossiers" / "cursor.md").exists()
        out = capsys.readouterr().out
        assert "档案已导出" in out or "1 份报告" in out
