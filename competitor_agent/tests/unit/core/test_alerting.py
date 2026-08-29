"""alerting 单测（设计文档 28 §5 diff/告警 + 67 §3.3 推送）：
两次报告价格 20→40 产出 price_change Alert（old/new/证据）；无变化无 Alert；
FileAlertSink 追加落盘 reports/alerts/<date>.md；ConsoleAlertSink 打印；
WebhookAlertSink mock POST 载荷正确、失败静默降级；CompositeAlertSink 失败不互扰；
EmailAlertSink mock smtplib。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from competitor_agent.core.alerting import (
    CompositeAlertSink,
    ConsoleAlertSink,
    EmailAlertSink,
    FileAlertSink,
    WebhookAlertSink,
    build_composite_sink,
    report_diff,
)
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


class TestWebhookAlertSink:
    def test_posts_json_payload(self) -> None:
        seen: dict[str, object] = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["method"] = request.method
            seen["json"] = json.loads(request.content)
            return httpx.Response(200)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        sink = WebhookAlertSink("https://hooks.example/x")
        sink._client = client  # type: ignore[attr-defined]
        alert = report_diff(_report(20), _report(40))[0]
        sink.emit(alert)
        assert seen["method"] == "POST"
        payload = seen["json"]
        assert payload["competitor"] == "cursor"
        assert payload["kind"] == "price_change"
        assert "价格" in payload["summary"] or "→" in payload["summary"]
        assert payload["evidence_urls"] == ["https://x.test/pricing"]

    def test_failure_silently_degraded(self, capsys: pytest.CaptureFixture[str]) -> None:
        def handler(request):
            raise httpx.ConnectError("boom")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        sink = WebhookAlertSink("https://hooks.example/x")
        sink._client = client  # type: ignore[attr-defined]
        sink.emit(report_diff(_report(20), _report(40))[0])  # 不抛
        out = capsys.readouterr().out
        assert "price_change" not in out  # 不打印告警内容，仅日志


class TestCompositeAlertSink:
    def test_emits_to_all_sinks(self) -> None:
        seen: list[str] = []

        class A:
            def emit(self, alert):
                seen.append("a")

        class B:
            def emit(self, alert):
                seen.append("b")

        sink = CompositeAlertSink(A(), B())
        sink.emit(report_diff(_report(20), _report(40))[0])
        assert seen == ["a", "b"]

    def test_one_failure_does_not_block_others(self) -> None:
        seen: list[str] = []

        class Boom:
            def emit(self, alert):
                raise RuntimeError("boom")

        class Ok:
            def emit(self, alert):
                seen.append("ok")

        sink = CompositeAlertSink(Boom(), Ok())
        sink.emit(report_diff(_report(20), _report(40))[0])  # 不抛
        assert seen == ["ok"]


class TestEmailAlertSink:
    def test_mock_smtplib_sends(self, monkeypatch) -> None:
        sent: dict[str, object] = {}

        class _FakeSMTP:
            def __init__(self, host, port, timeout=0):
                sent["host"] = host
                sent["port"] = port

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def login(self, u, p):
                sent["login"] = (u, p)

            def sendmail(self, frm, to, msg):
                sent["from"] = frm
                sent["to"] = to
                sent["msg"] = str(msg)

        import smtplib

        monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)
        sink = EmailAlertSink(
            host="smtp.example.com", port=465, from_addr="a@x.com",
            to_addrs=["b@x.com"], username="u", password="p",
        )
        sink.emit(report_diff(_report(20), _report(40))[0])
        assert sent["host"] == "smtp.example.com"
        assert sent["port"] == 465
        assert sent["from"] == "a@x.com"
        assert "b@x.com" in sent["to"]
        # MIME 正文 utf-8 base64 编码 → 解码后含告警内容
        import base64
        import email

        msg = email.message_from_string(sent["msg"])
        body = ""
        for part in msg.walk():
            if (part.get("Content-Transfer-Encoding") == "base64") and part.get_payload():
                body = base64.b64decode(part.get_payload()).decode("utf-8")
        assert "cursor" in body
        assert "price_change" in body

    def test_missing_config_skips(self, capsys: pytest.CaptureFixture[str]) -> None:
        sink = EmailAlertSink(host="smtp.x.com", from_addr="", to_addrs=[])
        sink.emit(report_diff(_report(20), _report(40))[0])  # 不抛

    def test_failure_silently_degraded(self, monkeypatch) -> None:
        class _FakeSMTP:
            def __init__(self, host, port, timeout=0):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def sendmail(self, *a):
                raise OSError("boom")

        import smtplib

        monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)
        sink = EmailAlertSink(host="smtp.x.com", port=465, from_addr="a@x.com", to_addrs=["b@x.com"])
        sink.emit(report_diff(_report(20), _report(40))[0])  # 不抛


class TestBuildCompositeSink:
    def test_includes_file_and_webhook(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("competitor_agent.core.alerting.FileAlertSink", lambda **kw: FileAlertSink(output_dir=tmp_path))
        sink = build_composite_sink(webhook_urls=["https://hooks.example/x"])
        assert isinstance(sink, CompositeAlertSink)
        assert len(sink._sinks) == 2  # FileAlertSink + WebhookAlertSink

    def test_ignores_invalid_webhook_and_empty_email(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("competitor_agent.core.alerting.FileAlertSink", lambda **kw: FileAlertSink(output_dir=tmp_path))
        sink = build_composite_sink(webhook_urls=["not-a-url"], email={"host": "", "from": "", "to": []})
        assert len(sink._sinks) == 1  # 只有 FileAlertSink

    def test_email_included_when_configured(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("competitor_agent.core.alerting.FileAlertSink", lambda **kw: FileAlertSink(output_dir=tmp_path))
        sink = build_composite_sink(
            webhook_urls=[],
            email={"host": "smtp.x.com", "port": 465, "from": "a@x.com", "to": ["b@x.com"]},
        )
        assert len(sink._sinks) == 2