"""竞品异动告警（设计文档 28 §3.3 / 67 §3.3）

``Alert`` 描述一次竞品变化（价格 / 功能 / 版本 / 榜单 / 路线图）；``AlertSink``
为输出协议，``FileAlertSink`` 追加写入 ``<data_dir>/reports/alerts/<date>.md``（控制台可用
``ConsoleAlertSink``）。``report_diff`` 复用设计文档 26 的 ``TimelineMemory.diff``
把时间线事件映射为告警。

设计文档 67 §3.3 推送通道：``WebhookAlertSink``（企业微信/钉钉/飞书机器人 POST JSON）、
``EmailAlertSink``（标准库 smtplib，无新依赖）、``CompositeAlertSink``（逐个 emit，
失败不互扰）；失败均静默降级记日志（守 doc 54 纪律）。
"""
from __future__ import annotations

import logging
import smtplib
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Protocol, cast

import httpx

from competitor_agent.secret_vault import get_reports_dir

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

    def to_dict(self) -> dict[str, object]:
        """推送载荷（Webhook/Email 通用）：竞品/kind/summary/old→new/证据/时间。"""
        return {
            "competitor": self.competitor,
            "kind": self.kind,
            "summary": self.summary,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "evidence_urls": list(self.evidence_urls),
            "occurred_at": self.occurred_at,
        }


class AlertSink(Protocol):
    """告警输出协议"""

    def emit(self, alert: Alert) -> None: ...


class ConsoleAlertSink:
    """打印告警到控制台（CRON/脚本场景可视化）"""

    def emit(self, alert: Alert) -> None:
        print(f"[alert:{alert.kind}] {alert.competitor}: {alert.summary}", flush=True)


class FileAlertSink:
    """追加写入 <data_dir>/reports/alerts/<date>.md（按日聚合，线程安全追加）。"""

    def __init__(self, output_dir: str | Path | None = None) -> None:
        if output_dir:
            self._dir = Path(output_dir).expanduser()
        else:
            self._dir = get_reports_dir() / "alerts"
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


class WebhookAlertSink:
    """POST JSON 告警载荷到 webhook（企业微信/钉钉/飞书机器人，同一 JSON 各自适配）。

    失败（网络/非 2xx/超时）静默降级记日志，不崩 ``run_scheduled``；超时读
    ``timeout`` 参数（默认 10s）。可注入 ``client`` 便于测试。
    """

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = url
        self._headers = headers or {"Content-Type": "application/json"}
        self._timeout = timeout
        self._client = client

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client()
        return self._client

    def emit(self, alert: Alert) -> None:
        try:
            resp = self._get_client().post(
                self._url,
                json=alert.to_dict(),
                headers=self._headers,
                timeout=self._timeout,
            )
            if resp.status_code >= 400:
                logger.warning("Webhook 推送 HTTP %s: %s", resp.status_code, resp.text[:200])
        except Exception:
            logger.warning("Webhook 推送失败（静默降级）: %s", self._url, exc_info=True)


class EmailAlertSink:
    """标准库 smtplib 邮件推送（无新依赖）。每次 emit 发一封；失败静默降级。"""

    def __init__(
        self,
        host: str,
        port: int = 465,
        from_addr: str = "",
        to_addrs: list[str] | tuple[str, ...] = (),
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = True,
    ) -> None:
        self._host = host
        self._port = int(port)
        self._from = from_addr
        self._to = list(to_addrs)
        self._username = username
        self._password = password
        self._use_tls = use_tls

    def emit(self, alert: Alert) -> None:
        if not self._from or not self._to:
            logger.warning("EmailAlertSink 未配置发件人/收件人，跳过")
            return
        body = (
            f"竞品: {alert.competitor}\n"
            f"类型: {alert.kind}\n"
            f"摘要: {alert.summary}\n"
            f"变化: {alert.old_value or '-'} → {alert.new_value or '-'}\n"
            f"证据: {', '.join(alert.evidence_urls[:3]) or '-'}\n"
            f"时间: {alert.occurred_at}"
        )
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"[竞品告警] {alert.competitor} {alert.kind}"
        msg["From"] = self._from
        msg["To"] = ", ".join(self._to)
        try:
            with smtplib.SMTP_SSL(self._host, self._port, timeout=15) if self._use_tls else \
                 smtplib.SMTP(self._host, self._port, timeout=15) as server:
                if self._username is not None:
                    server.login(self._username, self._password or "")
                server.sendmail(self._from, self._to, msg.as_string())
        except Exception:
            logger.warning("邮件推送失败（静默降级）: host=%s", self._host, exc_info=True)


class CompositeAlertSink:
    """复合输出：逐个 emit 到每个 sink，单个失败不影响后续（失败不互扰）。"""

    def __init__(self, *sinks: AlertSink) -> None:
        self._sinks: list[AlertSink] = list(sinks)

    def emit(self, alert: Alert) -> None:
        for sink in self._sinks:
            try:
                sink.emit(alert)
            except Exception:
                logger.warning("告警 sink 失败（不阻断）: %s", type(sink).__name__, exc_info=True)

    def extend(self, *sinks: AlertSink) -> None:
        self._sinks.extend(sinks)


def build_composite_sink(
    webhook_urls: list[str] | None = None,
    email: dict[str, object] | None = None,
    include_file: bool = True,
    timeout: float = 10.0,
) -> CompositeAlertSink:
    """按配置组装复合 sink：FileAlertSink（默认）+ webhook 列表 + 可选邮件。

    ``email`` 形如 ``{"host", "port", "from", "to", "username", "password"}``，
    缺 host/from/to 时跳过邮件推送（不配置不打扰）。
    """
    sinks: list[AlertSink] = []
    if include_file:
        sinks.append(FileAlertSink())
    for url in webhook_urls or []:
        if url and str(url).strip().startswith("http"):
            sinks.append(WebhookAlertSink(str(url).strip(), timeout=timeout))
    if email and str(email.get("host") or "") and str(email.get("from") or "") and (email.get("to") or []):
        raw_to = email.get("to") or []
        to_addrs = [str(t) for t in raw_to] if isinstance(raw_to, (list, tuple)) else []
        sinks.append(
            EmailAlertSink(
                host=str(email["host"]),
                port=int(str(email.get("port") or 465)),
                from_addr=str(email["from"]),
                to_addrs=to_addrs,
                username=str(email["username"]) if email.get("username") else None,
                password=str(email["password"]) if email.get("password") else None,
                use_tls=bool(email.get("use_tls", True)),
            )
        )
    return CompositeAlertSink(*sinks)


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

    # prev/cur 为 duck-type（不限于 CompetitorReport）；cast Any 兼容 TimelineMemory.diff
    # 的严格签名（孤立文件跑 mypy 时 follow_imports=skip 会让 ignore 判定为"未使用"，
    # 全仓跑时又会报 arg-type——cast 在两种上下文都稳定）。
    events = TimelineMemory.diff(cast(Any, prev), cast(Any, cur))
    return [_alert_from_event(e) for e in events]


__all__ = [
    "Alert",
    "AlertSink",
    "CompositeAlertSink",
    "ConsoleAlertSink",
    "EmailAlertSink",
    "FileAlertSink",
    "WebhookAlertSink",
    "build_composite_sink",
    "report_diff",
]
