"""observability/langfuse_exporter.py 单测（设计文档 54 §2.3）：
三变量不齐/依赖缺失 NoOp、mock SDK 上报字段映射、上报失败静默降级本地不受影响、
ObservabilityConfig.langfuse_enabled 派生属性各组合。"""
from __future__ import annotations

import os
from typing import Any

import pytest
from competitor_agent.config.loader import ObservabilityConfig
from competitor_agent.observability.langfuse_exporter import LangfuseExporter


class _FakeCM:
    """Langfuse ``start_as_observation`` 返回的 CM：__enter__ 即 recorder，__exit__ 落盘。"""

    def __init__(self, sink: list, kind: str, start: dict) -> None:
        self._sink = sink
        self._kind = kind
        self._start = start
        self.updated: dict | None = None

    def __enter__(self) -> "_FakeCM":
        return self

    def __exit__(self, *_: Any) -> None:
        self._sink.append({"type": self._kind, "start": self._start, "update": self.updated or {}})

    def update(self, **kw: Any) -> None:
        self.updated = kw


class FakeLangfuse:
    def __init__(self) -> None:
        self.traces: list[dict] = []
        self.spans: list[dict] = []
        self.gens: list[dict] = []
        self.fail_trace = False

    def trace(self, **kw: Any) -> None:
        if self.fail_trace:
            raise RuntimeError("上报失败")
        self.traces.append(kw)

    def start_as_observation(self, **kw: Any) -> _FakeCM:
        kind = kw.get("type") or "SPAN"
        sink = self.gens if kind == "GENERATION" else self.spans
        return _FakeCM(sink, kind, kw)


def _trace_record() -> dict:
    return {
        "kind": "trace", "trace_id": "sess_t", "name": "analyze", "span_id": "sess_t",
        "parent_span_id": None, "start": "2026-08-20T00:00:00.000+00:00",
        "end": "2026-08-20T00:00:01.000+00:00", "status": "success",
        "input_brief": "in", "output_brief": "out", "error": None,
    }


def _gen_record() -> dict:
    return {
        "kind": "llm", "trace_id": "sess_t", "span_id": "g1", "parent_span_id": "sess_t",
        "name": "llm.call", "start": "2026-08-20T00:00:00.000+00:00",
        "end": "2026-08-20T00:00:00.020+00:00", "status": "ok", "input_brief": "",
        "output_brief": "", "error": None, "model": "m", "prompt_tokens": 10,
        "completion_tokens": 5, "total_tokens": 15, "elapsed_ms": 20, "cost_usd": 0.0001,
        "attempts": 1, "retried": False, "timed_out": False,
    }


def _span_record() -> dict:
    return {
        "kind": "tool", "trace_id": "sess_t", "span_id": "sp", "parent_span_id": "sess_t",
        "name": "tool.web_extract", "start": "2026-08-20T00:00:00.000+00:00",
        "end": "2026-08-20T00:00:00.500+00:00", "status": "ok", "input_brief": "url",
        "output_brief": "", "error": None,
    }


class TestEnvReadyNoOp:
    def test_noop_without_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for k in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
            monkeypatch.delenv(k, raising=False)
        exp = LangfuseExporter()  # 构造不炸（无 SDK 依赖），emit no-op
        exp.emit(_trace_record())
        exp.flush()  # 不抛

    def test_partial_env_still_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3000")
        # 缺 public/secret → NoOp
        exp = LangfuseExporter()
        assert exp._client is None


class TestInjectedMapping:
    def test_trace_mapping(self) -> None:
        fake = FakeLangfuse()
        exp = LangfuseExporter(client=fake)
        exp.emit(_trace_record())
        exp.flush()
        assert fake.traces and fake.traces[0]["name"] == "analyze"
        assert fake.traces[0]["input"] == "in"

    def test_generation_mapping(self) -> None:
        fake = FakeLangfuse()
        exp = LangfuseExporter(client=fake)
        exp.emit(_gen_record())
        exp.flush()
        assert fake.gens, "期望 generation 上报到 GENERATION 观察"
        assert fake.gens[0]["type"] == "GENERATION"
        assert fake.gens[0]["start"]["name"] == "llm.call"
        assert fake.gens[0]["start"]["trace_id"] == "sess_t"

    def test_span_mapping(self) -> None:
        fake = FakeLangfuse()
        exp = LangfuseExporter(client=fake)
        exp.emit(_span_record())
        exp.flush()
        assert fake.spans and fake.spans[0]["type"] == "SPAN"
        assert fake.spans[0]["start"]["parent_observation_id"] == "sess_t"

    def test_failure_silently_degraded(self) -> None:
        fake = FakeLangfuse()
        fake.fail_trace = True
        exp = LangfuseExporter(client=fake)
        exp.emit(_trace_record())
        exp.flush()  # 不抛；trace 失败仅记 warning


class TestLangfuseEnabledProperty:
    def test_disabled_without_all_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for k in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
            monkeypatch.delenv(k, raising=False)
        assert ObservabilityConfig().langfuse_enabled is False

    def test_disabled_without_sdk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:3000")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        # langfuse 包通常未装（optional extra）→ False；若恰好装了则应是 True——
        # 这里用探测结果断言一致性，避免环境耦合
        import importlib.util

        sdk = importlib.util.find_spec("langfuse") is not None
        assert ObservabilityConfig().langfuse_enabled is sdk

    def test_partial_env_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:3000")
        for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
            monkeypatch.delenv(k, raising=False)
        assert ObservabilityConfig().langfuse_enabled is False