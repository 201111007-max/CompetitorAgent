"""§15 集成 — Web 报告展示/导出链路（设计文档 22 §5 集成 + Web e2e）

用 FakeExtractor + mock_llm 跑一次真实 analyze（走生产 _event_generator 链路）：
- report 事件 payload 含 markdown_report（与 CompetitorReport 一致）与 session_id；
- reports/competitor/<竞品>.md 自动落盘且含 "# <竞品> 竞品分析报告"。
Web 端点：/api/reports/{competitor} 未鉴权 401；download 返回 Content-Disposition。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from competitor_agent import web_app
from competitor_agent.config.loader import AppConfig
from competitor_agent.core import report_archiver as ra
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.memory import FourLayerMemory


class _ReportAPI:
    """Web 内真实 API 替身：delegate 到用 fake_extractor+mock_llm 构建的 API。"""

    def __init__(self, inner: CompetitorAnalysisAPI) -> None:
        self._inner = inner

    def analyze(self, task, conversation_history=None, mode="team", session_id=None):
        return self._inner.analyze(task, mode=mode, session_id=session_id)

    def run(self, task: str, *, session_id: str | None = None, history_messages=None):
        # 设计文档 62 §3.7：统一入口；单竞品任务委托给真实 analyze
        return self._inner.analyze(task, session_id=session_id)

    def compare(self, *competitors):
        raise AssertionError("单竞品任务不应走 compare")

    def discover(self, task):
        raise AssertionError("单竞品任务不应走 discover")

    def cancel(self, session_id: str) -> None:
        pass


def _sse_events(lines: list[str]) -> list[dict]:
    return [json.loads(l[len("data: "):]) for l in lines if l.startswith("data: ")]


class TestReportViaEventGenerator:
    def test_report_payload_and_auto_save(
        self,
        fake_extractor,
        mock_llm,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 落盘目录重定向到 tmp；Web 内记忆也重定向
        cfg = AppConfig()
        cfg.report.output_dir = str(tmp_path / "reports" / "competitor")
        monkeypatch.setattr(ra, "load_config", lambda: cfg)
        mem = FourLayerMemory(tmp_path / "memory")
        monkeypatch.setattr(web_app, "_get_memory", lambda: mem)

        inner = CompetitorAnalysisAPI(
            extractor=fake_extractor, llm=mock_llm, use_llm=True, max_iterations=10
        )
        monkeypatch.setattr(web_app, "CompetitorAnalysisAPI", lambda **kw: _ReportAPI(inner))
        # 设计文档 47：Web 内部路由 parse_task 亦走真实 LLM（无 Key 会抛错）。
        # 注入 mock_llm 保持生产 _event_generator 链路可复现（不触发真实网络/Key）。
        monkeypatch.setattr(web_app, "LLMClient", lambda **kwargs: mock_llm)

        sid = "sess_rep_export"
        lines: list[str] = []

        async def _run() -> None:
            nonlocal lines
            async for line in web_app._event_generator(sid, "分析 Cursor"):
                lines.append(line)

        asyncio.run(_run())

        events = _sse_events(lines)
        report_ev = [e for e in events if e["event"] == "report"]
        assert report_ev, f"SSE 缺 report 事件，实际: {[e['event'] for e in events]}"

        payload = report_ev[0]["payload"]
        assert payload["markdown_report"], "report payload 缺 markdown_report"
        assert payload["session_id"] == sid, "report payload 缺 session_id"
        assert payload["competitor"] == "cursor"

        f = tmp_path / "reports" / "competitor" / "cursor.md"
        assert f.exists(), f"报告未自动落盘: {f}"
        content = f.read_text(encoding="utf-8")
        assert "# cursor 竞品分析报告" in content
        assert content == payload["markdown_report"], "落盘内容与 SSE payload 不一致"


class TestReportWebEndpoints:
    def _write_report(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str = "cursor") -> None:
        out = tmp_path / "reports" / "competitor"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{name}.md").write_text(f"# {name} 竞品分析报告\n正文", encoding="utf-8")
        monkeypatch.setattr(web_app, "report_file_path", lambda n, **kw: out / f"{ra._safe_filename(n)}.md")

    def test_report_unauthorized_when_token_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(web_app._config.security, "auth_token", "secret-token")
        with TestClient(web_app.app) as client:
            resp = client.get("/api/reports/cursor")
        assert resp.status_code == 401

    def test_report_returns_content(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._write_report(tmp_path, monkeypatch)
        with TestClient(web_app.app) as client:
            resp = client.get("/api/reports/cursor")
        assert resp.status_code == 200
        assert "# cursor 竞品分析报告" in resp.text

    def test_report_missing_returns_404(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._write_report(tmp_path, monkeypatch)
        with TestClient(web_app.app) as client:
            resp = client.get("/api/reports/nonexistent")
        assert resp.status_code == 404

    def test_report_download_sets_attachment(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._write_report(tmp_path, monkeypatch)
        with TestClient(web_app.app) as client:
            resp = client.get("/api/reports/cursor/download")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert "cursor.md" in resp.headers.get("content-disposition", "")
        assert "# cursor 竞品分析报告" in resp.text
