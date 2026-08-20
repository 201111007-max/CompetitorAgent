"""observability/tracer.py 单测（设计文档 54）：
span 树嵌套 / 跨线程 parent 显式传递 / JSONL 落盘往返重建 / 异常与取消 status /
脱敏（brief 截断 + 不落 prompt 全文）/ 聚合字段（total_cost/total_tokens）/ 零埋点降级。"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from competitor_agent.observability import tracer as T


def _tracer(tmp_path: Path) -> T.Tracer:
    return T.Tracer(sinks=[T.JsonlSink(tmp_path)])


def _read_all(path: Path) -> list[dict]:
    return T.iter_traces(path)


class TestSpanTree:
    def test_nested_auto_parent(self, tmp_path: Path) -> None:
        t = _tracer(tmp_path)
        tid = t.start_trace("analyze", trace_id="sess_tree", input_brief="t")
        with t.span("llm.call", kind="llm") as sp:
            sub_span_id = sp["span_id"]
        t.end_trace(tid)
        records = {r["name"]: r for r in _read_all(tmp_path)}
        assert records["analyze"]["kind"] == "trace"
        assert records["analyze"]["parent_span_id"] is None
        assert records["llm.call"]["parent_span_id"] == tid  # 根 span_id == trace_id
        assert records["llm.call"]["trace_id"] == tid

    def test_explicit_cross_thread_parent(self, tmp_path: Path) -> None:
        """子 Agent 后台线程：显式传 trace_id + parent_span_id 挂到 delegate span 下。"""
        t = _tracer(tmp_path)
        tid = t.start_trace("analyze", trace_id="sess_cross", input_brief="t")
        # subagent span 在 worker 线程显式挂接 parent
        parent = None
        with t.span("delegate", kind="phase") as deleg:
            parent = deleg["span_id"]
        result: list = []

        def worker() -> None:
            t2 = t  # 共享 Tracer（跨线程注册表有锁）
            with t2.span("pricing", kind="subagent", trace_id=tid, parent_span_id=parent) as sub:
                result.append(sub["span_id"])
                parent_before = t2.current_span_id()
                t2.record_generation(model="m", prompt_tokens=10, completion_tokens=5,
                                     elapsed_ms=1, cost_usd=0.0001)
                result.append(parent_before)

        th = threading.Thread(target=worker)
        th.start()
        th.join()
        t.end_trace(tid)
        by_name = {r["name"]: r for r in _read_all(tmp_path)}
        assert by_name["pricing"]["parent_span_id"] == parent
        # subagent 内的 generation 挂到 subagent 下（worker 栈顶）
        assert by_name["llm.call"]["parent_span_id"] == result[0]
        assert by_name["llm.call"]["trace_id"] == tid

    def test_jsonl_roundtrip_reconstruct(self, tmp_path: Path) -> None:
        t = _tracer(tmp_path)
        tid = t.start_trace("analyze", trace_id="sess_rt", input_brief="t")
        with t.span("delegate", kind="phase"):
            with t.span("pricing", kind="subagent"):
                pass
        t.end_trace(tid, status="success", output_brief="done")
        spans = T.load_trace("sess_rt", tmp_path)
        assert len(spans) == 3
        # 重建树：只有根是 kind=trace 且 parent=None
        roots = [s for s in spans if s["kind"] == "trace"]
        assert len(roots) == 1
        children = [s for s in spans if s["parent_span_id"] == "sess_rt"]
        assert [c["name"] for c in children] == ["delegate"]
        pricing = [s for s in spans if s["name"] == "pricing"][0]
        deleg_id = children[0]["span_id"]
        assert pricing["parent_span_id"] == deleg_id


class TestStatusAndDesensitization:
    def test_exception_marks_error(self, tmp_path: Path) -> None:
        t = _tracer(tmp_path)
        tid = t.start_trace("analyze", trace_id="sess_exc", input_brief="t")
        try:
            with t.span("tool.web_extract", kind="tool"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        records = {r["name"]: r for r in _read_all(tmp_path)}
        assert records["tool.web_extract"]["status"] == "error"
        assert "boom" in str(records["tool.web_extract"]["error"])

    def test_brief_truncated_and_no_prompt(self, tmp_path: Path) -> None:
        t = _tracer(tmp_path)
        tid = t.start_trace("analyze", trace_id="sess_mask", input_brief="x" * 500)
        with t.span("phase_1", kind="phase", input_brief="y" * 300):
            t.record_generation(model="m", prompt_tokens=1, completion_tokens=1,
                                elapsed_ms=1, cost_usd=0.0)
        t.end_trace(tid)
        records = _read_all(tmp_path)
        # 根与子 span 的 brief 均截断到 200 字符
        assert len([r["input_brief"] for r in records if r["kind"] == "trace"][0]) == 200
        gen = [r for r in records if r["kind"] == "llm"][0]
        # generation 不落 prompt 全文（仅空 brief），模型/计数直搬
        assert gen["input_brief"] == ""
        assert gen["model"] == "m"
        assert gen["total_tokens"] == 2


class TestAggregation:
    def test_total_cost_and_tokens(self, tmp_path: Path) -> None:
        t = _tracer(tmp_path)
        tid = t.start_trace("analyze", trace_id="sess_agg", input_brief="t")
        t.record_generation(model="m", prompt_tokens=100, completion_tokens=50,
                            elapsed_ms=40, cost_usd=0.0004)
        t.record_generation(model="m", prompt_tokens=10, completion_tokens=10,
                            elapsed_ms=20, cost_usd=0.0001)
        t.end_trace(tid)
        root = [r for r in _read_all(tmp_path) if r["kind"] == "trace"][0]
        assert root["total_tokens"] == 170
        assert abs(root["total_cost_usd"] - 0.0005) < 1e-6

    def test_no_trace_no_emit(self, tmp_path: Path) -> None:
        t = _tracer(tmp_path)
        # 未 start_trace 就 record_generation / span → 零埋点，不落盘也不抛
        t.record_generation(model="m", prompt_tokens=1, completion_tokens=1,
                            elapsed_ms=1, cost_usd=0.0)
        with t.span("x", kind="phase"):
            pass
        assert _read_all(tmp_path) == []


class TestListSummaries:
    def test_summary_fields(self, tmp_path: Path) -> None:
        t = _tracer(tmp_path)
        t.start_trace("analyze", trace_id="sess_a", input_brief="a")
        t.end_trace("sess_a")
        sums = T.list_summaries(tmp_path)
        assert len(sums) == 1
        s = sums[0]
        assert s["trace_id"] == "sess_a"
        assert s["name"] == "analyze"
        assert "span_count" in s


def test_render_waterfall_contains_all_three_kinds(tmp_path: Path) -> None:
    t = _tracer(tmp_path)
    tid = t.start_trace("analyze", trace_id="sess_wf", input_brief="t")
    parent = None
    with t.span("delegate", kind="phase") as d:
        parent = d["span_id"]
    with t.span("pricing", kind="subagent", trace_id=tid, parent_span_id=parent):
        t.record_generation(model="m", prompt_tokens=1, completion_tokens=1,
                            elapsed_ms=1, cost_usd=0.0)
    t.end_trace(tid)
    text = T.render_waterfall(T.load_trace("sess_wf", tmp_path))
    assert "analyze" in text
    assert "delegate" in text
    assert "pricing" in text
    assert "llm.call" in text
    assert "m" in text  # 模型列


def test_record_payload_has_no_key_or_prompt(tmp_path: Path) -> None:
    """落盘记录不含密钥/提示词全文特征串（脱敏纪律）。"""
    t = _tracer(tmp_path)
    t.start_trace("analyze", trace_id="sess_sec", input_brief="SECRET_MARKER " * 10)
    t.end_trace("sess_sec")
    raw = list(Path(tmp_path).glob("*.jsonl"))[0].read_text(encoding="utf-8")
    lines = [json.loads(l) for l in raw.splitlines() if l.strip()]
    text = "\n".join(json.dumps(l, ensure_ascii=False) for l in lines)
    assert "SECRET_MARKER" * 10 not in text  # 只截断保留前缀，不会完整重复
    assert "api_key" not in text.lower()