"""observability/logger.py 单测（设计文档 21）：
JSON 结构化格式、会话级落盘、auto_flush 不缓冲、读日志助手。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from competitor_agent.observability import logger as L


@pytest.fixture(autouse=True)
def _isolated_logging(tmp_path: Path) -> Path:
    """每个测试用独立日志目录，隔离全局状态。"""
    log_dir = tmp_path / "logs"
    L.setup_logging(level="INFO", log_dir=log_dir, json_format=True)
    L._session_adapters.clear()
    yield log_dir
    # 重置根 handler，避免污染其它测试
    root = __import__("logging").getLogger("competitor_agent")
    for h in list(root.handlers):
        root.removeHandler(h)
    L._configured = False


class TestJSONFormatter:
    def test_json_line_contains_session_and_phase(self, tmp_path: Path) -> None:
        L.set_current_session("sess_fmt_1")
        slog = L.get_session_logger()
        L.log_event(slog, "collect.done", "collect", "采集完成", url="https://a.com", bytes=12)
        L.close_session_log("sess_fmt_1")
        L.set_current_session(None)

        path = L.log_file_path("sess_fmt_1")
        assert path.exists()
        line = path.read_text(encoding="utf-8").splitlines()[0]
        data = json.loads(line)
        assert data["session_id"] == "sess_fmt_1"
        assert data["event"] == "collect.done"
        assert data["phase"] == "collect"
        assert data["url"] == "https://a.com"
        assert data["bytes"] == 12
        assert data["message"] == "采集完成"

    def test_explicit_session_id_adapter(self) -> None:
        slog = L.get_session_logger("sess_explicit")
        L.log_event(slog, "task.parsed", "parse", "解析完成", competitors=["Cursor"])
        L.close_session_log("sess_explicit")
        data = json.loads(L.log_file_path("sess_explicit").read_text(encoding="utf-8").splitlines()[0])
        assert data["session_id"] == "sess_explicit"
        assert data["competitors"] == ["Cursor"]


class TestDetachedFlush:
    def test_log_lands_even_when_stdout_detached(self, tmp_path: Path) -> None:
        """auto_flush 下，日志直写文件，不受 stdout 缓冲/重定向影响（模拟 detached）。"""
        code = (
            "import sys, json\n"
            "from pathlib import Path\n"
            "from competitor_agent.observability import logger as L\n"
            "L.setup_logging(log_dir=sys.argv[1])\n"
            "slog = L.get_session_logger('sess_detached')\n"
            "L.log_event(slog, 'report.built', 'report', '生成报告', dimension_count=3)\n"
            "L.close_session_log('sess_detached')\n"
        )
        log_dir = tmp_path / "detached_logs"
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[4])}
        result = subprocess.run(
            [sys.executable, "-c", code, str(log_dir)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            check=True,
        )
        assert result.returncode == 0, result.stderr
        path = log_dir / "sess_detached.log"
        assert path.exists(), "detached 场景会话日志未实时落盘"
        data = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert data["event"] == "report.built"


class TestReadSessionLog:
    def test_read_session_log_tail(self) -> None:
        slog = L.get_session_logger("sess_read")
        for i in range(5):
            L.log_event(slog, "step", "", f"step {i}", i=i)
        L.close_session_log("sess_read")
        lines = L.read_session_log("sess_read")
        assert len(lines) == 5
        tail = L.read_session_log("sess_read", tail=2)
        assert len(tail) == 2
        assert tail[-1]["i"] == 4

    def test_missing_session_returns_empty(self) -> None:
        assert L.read_session_log("sess_not_exist") == []


class TestTextFormatFallback:
    def test_text_format_when_json_disabled(self, tmp_path: Path) -> None:
        L.setup_logging(level="INFO", log_dir=tmp_path / "txt", json_format=False)
        slog = L.get_session_logger("sess_txt")
        L.log_event(slog, "collect.done", "collect", "采集完成")
        L.close_session_log("sess_txt")
        raw = L.log_file_path("sess_txt").read_text(encoding="utf-8").splitlines()[0]
        assert "采集完成" in raw
        assert "collect.done" in raw
