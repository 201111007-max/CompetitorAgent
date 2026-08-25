"""cli `trace` 子命令单测（设计文档 54 Q3）：list 空/有数据、show 瀑布渲染、parser 选项。"""
from __future__ import annotations

from pathlib import Path

import pytest
from competitor_agent.cli import _run_trace, build_parser
from competitor_agent.observability import tracer as T


@pytest.fixture(autouse=True)
def _isolate_traces_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 get_data_dir() 指向 tmp，隔离真实 ~/.competitor_agent/traces。"""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(T, "get_data_dir", lambda: data_dir)
    return data_dir


def _seed_trace(tmp_path: Path) -> str:
    """写入一条含 analysis/delegate/subagent/llm 的 trace，返回 trace_id。"""
    d = tmp_path / "data" / "traces"
    d.mkdir(parents=True, exist_ok=True)
    t = T.Tracer(sinks=[T.JsonlSink(d)])
    tid = t.start_trace("analyze", trace_id="sess_cli", input_brief="分析 cursor")
    parent = None
    with t.span("delegate", kind="phase") as deleg:
        parent = deleg["span_id"]
    with t.span("subagent", kind="subagent", trace_id=tid, parent_span_id=parent):
        t.record_generation(model="m", prompt_tokens=1, completion_tokens=1,
                            elapsed_ms=1, cost_usd=0.0)
    t.end_trace(tid)
    return tid


class TestTraceList:
    def test_empty_prints_hint(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        assert _run_trace("list", None) == 0
        out = capsys.readouterr().out
        assert "暂无 trace" in out

    def test_list_shows_summary(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        _seed_trace(tmp_path)
        _run_trace("list", None)
        out = capsys.readouterr().out
        assert "sess_cli" in out
        assert "analyze" in out


class TestTraceShow:
    def test_unknown_sid_prints_hint(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        _run_trace("show", "nonexistent")
        out = capsys.readouterr().out
        assert "无记录" in out

    def test_wrong_usage_requires_sid(self, capsys: pytest.CaptureFixture) -> None:
        _run_trace("show", None)
        out = capsys.readouterr().out
        assert "用法" in out

    def test_waterfall_renders_kinds(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        _seed_trace(tmp_path)
        _run_trace("show", "sess_cli")
        out = capsys.readouterr().out
        assert "analyze" in out
        assert "delegate" in out
        assert "subagent" in out
        assert "llm.call" in out


class TestParser:
    def test_trace_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["trace"])
        assert args.command == "trace"
        assert args.action == "list"

    def test_trace_show_args(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["trace", "show", "sess_abc"])
        assert args.action == "show"
        assert args.sid == "sess_abc"