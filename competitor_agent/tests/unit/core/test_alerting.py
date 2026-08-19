"""alerting 单测（设计文档 28 §5 diff/告警）：
两次报告价格 20→40 产出 price_change Alert（old/new/证据）；无变化无 Alert；
FileAlertSink 追加落盘 reports/alerts/<date>.md；ConsoleAlertSink 打印。"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from competitor_agent.core.alerting import ConsoleAlertSink, FileAlertSink, report_diff
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.observation import SourceEvidence
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _report(price: float, url: str = "https://x.test/pricing", created: str | None = None) -> CompetitorReport:
    return CompetitorReport(
        competitor=Competitor(name="cursor"),
        dimension_results=[
            DimensionResult(
                dimension="pricing",
                summary=f"价格 {price}/mo",
                details={
                    "pricing": {
                        "plans": [{"tier": "pro", "monthly_price_usd": price}],
                        "usage": {"per_unit_usd": price},
                    }
                },
                confidence=0.8,
                evidence=[SourceEvidence(source_name="web", url=url)],
                timestamp=created or _iso(),
            )
        ],
        created_at=created or _iso(),
    )


class TestReportDiff:
    def test_price_change_produces_alert(self) -> None:
        alerts = report_diff(_report(20), _report(40))
        assert len(alerts) == 1
        a = alerts[0]
        assert a.kind == "price_change"
        assert "价格变化" in a.summary or "→" in a.summary
        assert a.competitor == "cursor"
        assert a.evidence_urls == ["https://x.test/pricing"]

    def test_no_change_no_alert(self) -> None:
        assert report_diff(_report(20), _report(20)) == []

    def test_no_baseline_no_alert(self) -> None:
        # prev=审无快照（空报告）→ diff 对不到基线不产事件
        prev = CompetitorReport(competitor=Competitor(name="cursor"))
        assert report_diff(prev, _report(20)) == []


class TestFileAlertSink:
    def test_appends_dated_file(self, tmp_path: Path) -> None:
        sink = FileAlertSink(output_dir=tmp_path)
        alert = report_diff(_report(20), _report(40))[0]
        sink.emit(alert)
        sink.emit(alert)
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert content.count("价格变化") == 2
        assert "cursor" in content
        assert "https://x.test/pricing" in content

    def test_console_sink_prints(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        ConsoleAlertSink().emit(report_diff(_report(20), _report(40))[0])
        out = capsys.readouterr().out
        assert "price_change" in out
        assert "cursor" in out