"""设计文档 80：跑分口径 provenance——采集/工具/渲染/时间线/告警全链路标注。

留空即诚实：解析不到的口径字段留空并在展示层显式「口径未声明」（doc 47 纪律）；
口径不完整的 score_change 告警降级 info（防「换模型版本」被当成「竞品暴涨」）。
"""

from __future__ import annotations

from competitor_agent.collector.benchmark_sources import (
    BenchmarkHit,
    _parse_leaderboard_table,
)
from competitor_agent.core.alerting import report_diff
from competitor_agent.core.markdown_renderer import MarkdownRenderer
from competitor_agent.domain_types.benchmark import (
    first_benchmark_entry,
    has_vendor_self_reported,
    provenance_complete,
    provenance_note,
    provenance_note_from_entry,
)
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult
from competitor_agent.memory.timeline_memory import TimelineMemory

_HTML_WITH_PROVENANCE = """
<table>
  <tr><th>Model</th><th>% Resolved</th><th>Scaffold</th><th>Model Version</th><th>Date</th></tr>
  <tr><td>Claude Code</td><td>77.8%</td><td>v2.1</td><td>claude-5</td><td>2026-09-01</td></tr>
</table>
"""

_HTML_PLAIN = """
<table>
  <tr><th>Model</th><th>Score</th><th>Rank</th></tr>
  <tr><td>Codex</td><td>52.0</td><td>1</td></tr>
</table>
"""


class TestProvenanceHelpers:
    def test_note_full(self) -> None:
        note = provenance_note(
            source_type="third_party",
            provider_name="swebench",
            scaffold_version="v2.1",
            model_version="claude-5",
            collected_at="2026-09-08T10:00:00+00:00",
        )
        assert note == "[口径: 第三方实测·swebench·scaffold=v2.1·model=claude-5·collected=2026-09-08]"

    def test_note_vendor(self) -> None:
        assert "厂商自报" in provenance_note(source_type="vendor_self_reported")

    def test_note_undeclared(self) -> None:
        assert provenance_note() == "[口径未声明]"
        assert provenance_note_from_entry({"source_type": "", "fetched_at": ""}) == "[口径未声明]"

    def test_note_from_entry(self) -> None:
        note = provenance_note_from_entry(
            {"source_type": "vendor_self_reported", "fetched_at": "2026-09-08T00:00:00Z"}
        )
        assert "厂商自报" in note
        assert "collected=2026-09-08" in note

    def test_completeness(self) -> None:
        assert provenance_complete({"source_type": "third_party", "model_version": "gpt-6"})
        assert not provenance_complete({"source_type": "third_party"})  # 缺 model_version
        assert not provenance_complete({"model_version": "gpt-6"})  # 缺 source_type
        assert not provenance_complete("非 dict")

    def test_first_benchmark_entry_and_vendor_flag(self) -> None:
        details = {"benchmarks": [{"source_type": "vendor_self_reported"}]}
        assert first_benchmark_entry(details) == {"source_type": "vendor_self_reported"}
        assert has_vendor_self_reported(details)
        assert not has_vendor_self_reported({"benchmarks": [{"source_type": "third_party"}]})
        assert not has_vendor_self_reported(None)


class TestHitParsing:
    def test_hit_defaults_and_note(self) -> None:
        hit = BenchmarkHit(benchmark="swe-bench", rank="1", model="m", score="52", date="", source_url="u")
        assert hit.source_type == "third_party"
        note = hit.provenance_note()
        assert "第三方实测" in note
        assert "collected=" in note

    def test_parse_with_provenance_columns(self) -> None:
        hits = _parse_leaderboard_table(_HTML_WITH_PROVENANCE, "swe-bench", "https://x")
        assert len(hits) == 1
        hit = hits[0]
        assert hit.scaffold_version == "v2.1"
        assert hit.model_version == "claude-5"
        assert hit.provider_name == "swe-bench"
        assert hit.source_type == "third_party"

    def test_parse_without_provenance_columns_leaves_empty(self) -> None:
        """doc 80 §4.1：榜单无口径列 → 留空不报错（留空即诚实）。"""
        hits = _parse_leaderboard_table(_HTML_PLAIN, "swe-bench", "https://x")
        assert len(hits) == 1
        assert hits[0].scaffold_version == ""
        assert hits[0].model_version == ""

    def test_to_dict_carries_provenance(self) -> None:
        hit = BenchmarkHit(
            benchmark="aider", rank="2", model="m", score="60", date="", source_url="u",
            source_type="vendor_self_reported", scaffold_version="v3", model_version="m2",
        )
        data = hit.to_dict()
        assert data["source_type"] == "vendor_self_reported"
        assert data["scaffold_version"] == "v3"


class TestToolOutput:
    def test_benchmark_scores_appends_provenance_note(self, monkeypatch) -> None:
        """doc 80 §4.2：工具输出每行带口径尾注（str→str 契约不变）。"""
        from competitor_agent.mcp_server.tools import benchmark_tools

        hit = BenchmarkHit(
            benchmark="swe-bench", rank="1", model="Claude Code", score="77.8", date="2026-09-01",
            source_url="https://x", source_type="third_party", provider_name="swebench",
            scaffold_version="v2.1", model_version="claude-5",
        )
        monkeypatch.setattr(
            benchmark_tools, "build_benchmark_provider", lambda cfg, vault=None: _FakeProvider([hit])
        )
        out = benchmark_tools.benchmark_scores("swebench")
        assert "#77.8" not in out and "77.8" in out
        assert "[口径: 第三方实测·swebench·scaffold=v2.1·model=claude-5" in out
        assert "collected=" in out

    def test_benchmark_scores_undeclared_note(self, monkeypatch) -> None:
        from competitor_agent.mcp_server.tools import benchmark_tools

        hit = BenchmarkHit(
            benchmark="swe-bench", rank="1", model="m", score="52", date="", source_url="u",
            provider_name="swebench",
        )
        monkeypatch.setattr(
            benchmark_tools, "build_benchmark_provider", lambda cfg, vault=None: _FakeProvider([hit])
        )
        out = benchmark_tools.benchmark_scores("")
        assert "[口径: 第三方实测·swebench" in out  # provider/来源类型仍可见


class _FakeProvider:
    def __init__(self, hits: list[BenchmarkHit]) -> None:
        self._hits = hits

    def fetch(self, benchmark: str) -> list[BenchmarkHit]:
        return self._hits


class TestRenderer:
    def _report(self, benchmarks: list[dict]) -> CompetitorReport:
        result = DimensionResult(
            dimension="performance",
            summary="榜单表现",
            details={"benchmarks": benchmarks},
            confidence=0.8,
            status=ResultStatus.COMPLETE,
        )
        return CompetitorReport(competitor=Competitor(name="cursor"), dimension_results=[result])

    def test_vendor_self_reported_gets_warning(self) -> None:
        md = MarkdownRenderer().render(
            self._report([{"model": "Z Code", "score": "77.8", "source_type": "vendor_self_reported"}])
        )
        assert "> ⚠ 以下含厂商自报口径数据，未经第三方复核" in md

    def test_third_party_no_warning(self) -> None:
        """doc 80 §4.3：第三方实测无 ⚠ 引导行。"""
        md = MarkdownRenderer().render(
            self._report([{"model": "Codex", "score": "52", "source_type": "third_party"}])
        )
        assert "厂商自报" not in md


class TestTimelineProvenance:
    def _report(self, benchmarks: list[dict]) -> CompetitorReport:
        result = DimensionResult(
            dimension="performance",
            summary=f"榜单 {benchmarks[0]['score'] if benchmarks else '-'}",
            details={"benchmarks": benchmarks},
            confidence=0.8,
        )
        return CompetitorReport(competitor=Competitor(name="cursor"), dimension_results=[result])

    def test_score_change_summary_carries_note(self, tmp_path) -> None:
        """doc 80 §4.4：score_change 事件摘要带口径尾注（周报行复用事件摘要自动携带）。"""
        timeline = TimelineMemory(data_dir=tmp_path)
        timeline.update(self._report([{"model": "m", "score": "50"}]))
        events = timeline.update(
            self._report(
                [{"model": "m", "score": "55", "source_type": "third_party", "scaffold_version": "v2"}]
            )
        )
        score_events = [e for e in events if e.event_type == "score_change"]
        assert score_events, f"应产生 score_change 事件: {[e.event_type for e in events]}"
        assert "[口径: 第三方实测" in score_events[0].summary
        assert "scaffold=v2" in score_events[0].summary

    def test_score_change_without_provenance_declared_undeclared(self, tmp_path) -> None:
        timeline = TimelineMemory(data_dir=tmp_path)
        timeline.update(self._report([{"model": "m", "score": "50"}]))
        events = timeline.update(self._report([{"model": "m", "score": "58"}]))
        score_events = [e for e in events if e.event_type == "score_change"]
        assert score_events and "[口径未声明]" in score_events[0].summary


class TestAlertDowngrade:
    """doc 80 §4.5：口径不完整的 score_change → info 级。"""

    def _pair(self, benchmarks: list[dict]):
        prev = CompetitorReport(
            competitor=Competitor(name="cursor"),
            dimension_results=[
                DimensionResult(dimension="performance", summary="s1", details={"benchmarks": [{"score": "50"}]}, confidence=0.8)
            ],
        )
        cur = CompetitorReport(
            competitor=Competitor(name="cursor"),
            dimension_results=[
                DimensionResult(dimension="performance", summary="s2", details={"benchmarks": benchmarks}, confidence=0.8)
            ],
        )
        return prev, cur

    def test_incomplete_provenance_downgrades_to_info(self) -> None:
        prev, cur = self._pair([{"score": "55"}])  # 缺 source_type/model_version
        alerts = report_diff(prev, cur)
        score_alerts = [a for a in alerts if a.kind == "score_change"]
        assert score_alerts and all(a.severity == "info" for a in score_alerts)

    def test_complete_provenance_stays_warn(self) -> None:
        prev, cur = self._pair(
            [{"score": "55", "source_type": "third_party", "model_version": "gpt-6"}]
        )
        alerts = report_diff(prev, cur)
        score_alerts = [a for a in alerts if a.kind == "score_change"]
        assert score_alerts and all(a.severity == "warn" for a in score_alerts)

    def test_payload_carries_severity(self) -> None:
        from competitor_agent.core.alerting import Alert

        assert Alert(competitor="c", kind="score_change", summary="s").to_dict()["severity"] == "warn"
        assert (
            Alert(competitor="c", kind="score_change", summary="s", severity="info").to_dict()["severity"]
            == "info"
        )


class TestPromptGuidance:
    def test_performance_subagent_prompt_has_provenance_discipline(self) -> None:
        from competitor_agent.agent.prompts.react_system import build_subagent_system_prompt

        prompt = build_subagent_system_prompt("performance")
        assert "跑分口径" in prompt
        assert "口径未声明" in prompt

    def test_non_performance_prompt_no_provenance_block(self) -> None:
        from competitor_agent.agent.prompts.react_system import build_subagent_system_prompt

        assert "跑分口径纪律" not in build_subagent_system_prompt("pricing")

    def test_candidate_prompt_mentions_source_type(self) -> None:
        from competitor_agent.agent.prompts.react_system import build_subagent_system_prompt

        prompt = build_subagent_system_prompt("Some Agent")
        assert "source_type" in prompt


class TestWeeklyRowRides:
    def test_weekly_score_rows_include_note(self, tmp_path, monkeypatch) -> None:
        """doc 80 §4.4：周报 score_changes 行复用事件摘要 → 口径尾注自动携带。"""
        import json as _json

        # 造两份历史报告 JSON + 时间线事件，走 WeeklyReportBuilder
        from competitor_agent.core.weekly_report import WeeklyReportBuilder
        from competitor_agent.memory.timeline_memory import TimelineMemory

        reports_dir = tmp_path / "competitor"
        reports_dir.mkdir()
        timeline = TimelineMemory(data_dir=tmp_path)
        old = self._report_static([{"model": "m", "score": "50"}])
        new = self._report_static(
            [{"model": "m", "score": "55", "source_type": "third_party", "scaffold_version": "v2"}]
        )
        timeline.update(old)
        timeline.update(new)
        for name, rep in (("cursor_old", old), ("cursor", new)):
            (reports_dir / f"{name}.json").write_text(
                _json.dumps(
                    {
                        "competitor": {"name": rep.competitor.name},
                        "dimension_results": [
                            {"dimension": r.dimension, "summary": r.summary, "details": r.details,
                             "confidence": r.confidence, "timestamp": r.timestamp}
                            for r in rep.dimension_results
                        ],
                        "created_at": rep.created_at,
                        "overall_confidence": rep.overall_confidence,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        builder = WeeklyReportBuilder(reports_dir=str(reports_dir), window_days=7, data_dir=tmp_path)
        data = builder.build()
        rows = data.get("score_changes") or []
        assert rows, "周报应包含榜单分数变化行"
        assert any("[口径" in str(row) for row in rows)

    @staticmethod
    def _report_static(benchmarks: list[dict]) -> CompetitorReport:
        return CompetitorReport(
            competitor=Competitor(name="cursor"),
            dimension_results=[
                DimensionResult(
                    dimension="performance",
                    summary=f"榜单 {benchmarks[0].get('score')}",
                    details={"benchmarks": benchmarks},
                    confidence=0.8,
                )
            ],
        )
