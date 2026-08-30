"""设计文档 50 P0/P1：SSE 事件桥修复回归测试

覆盖三件事：
① 中途事件断言（本 bug 的回归测试）：分析在工作线程（run_in_executor）内通过 event_sink
   发事件——修复前 `asyncio.get_event_loop()` 在非主线程抛 RuntimeError 被静默吞掉，
   中途 phase_start/子 Agent 进度事件全部丢失（已实证）；修复后必须按序出现在 SSE 流。
② drain 语义：分析完成瞬间队列残余事件不丢失。
③ 取消响应：从 set_cancel 到 SSE 收到 cancelled 事件 ≤ 上界（设计目标 ≤300ms，nominal 0.2s 超时）。
"""
from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest
from competitor_agent import web_app
from competitor_agent.core.checkpoint import clear_cancel, is_cancelled, set_cancel
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.domain_types.report import CancelledResult, CompetitorReport

# 取消响应上界（秒）：nominal 队列超时 0.2s + 事件调度开销；CI 宽松留余量
_CANCEL_RESPONSE_BOUND = 0.5


class EmitAPI:
    """模拟分析：在工作线程内经 event_sink/stream_sink 发中途事件后返回正常报告。"""

    started = threading.Event()

    def __init__(self, *args, **kwargs) -> None:
        self.event_sink = kwargs.get("event_sink")
        self.stream_sink = kwargs.get("stream_sink")

    def analyze(
        self,
        task: str,
        conversation_history=None,
        mode: str = "team",
        session_id: str | None = None,
    ) -> CompetitorReport:
        from competitor_agent.llm.client import StreamDelta

        type(self).started.set()
        # 与生产一致：分析在 run_in_executor 工作线程执行，event_sink/stream_sink 回调
        # 发生在该线程。修复前在此调用会触发 get_event_loop() 的 RuntimeError → 事件全丢。
        self.stream_sink(StreamDelta(kind="text", text="正在分析"))
        for i in range(3):
            self.event_sink(
                ProgressEvent(
                    event="phase_start",
                    phase="react",
                    message=f"Lead 编排: 中途任务{i}",
                )
            )
        return CompetitorReport(
            competitor=Competitor(name="cursor"),
            dimension_results=[],
            terminal_state="success",
            overall_confidence=0.8,
            markdown_report="# Cursor 报告\n测试内容",
        )

    def run(
        self,
        task: str,
        *,
        session_id: str | None = None,
        history_messages: list[dict[str, str]] | None = None,
    ) -> CompetitorReport:
        """统一入口 stub（设计文档 62 §3.7）：单竞品任务委托给 analyze。"""
        return self.analyze(task, session_id=session_id)

    def cancel(self, session_id: str) -> None:
        set_cancel(session_id)


class SlowCancelAPI(EmitAPI):
    """取消测试专用：分析运行中等待取消标志，感知后返回 CancelledResult。"""

    def analyze(
        self,
        task: str,
        conversation_history=None,
        mode: str = "team",
        session_id: str | None = None,
    ) -> CancelledResult:
        type(self).started.set()
        while not is_cancelled(session_id):
            time.sleep(0.005)
        return CancelledResult(
            competitor=Competitor(name="cursor"),
            terminal_state="cancelled",
            cancelled=True,
        )


def _patch_env(monkeypatch: pytest.MonkeyPatch, mock_llm, api_cls, tmp_memory) -> None:
    """装配测试环境：替换真实 API/LLM/记忆/落盘，保持生产 _event_generator 链路。"""
    monkeypatch.setattr(web_app, "CompetitorAnalysisAPI", api_cls)
    monkeypatch.setattr(web_app, "LLMClient", lambda **kwargs: mock_llm)
    monkeypatch.setattr(web_app, "_get_memory", lambda: tmp_memory)
    monkeypatch.setattr(web_app, "save_report_markdown", lambda *a, **k: None)


def _collect(sse_lines: list[str]) -> list[dict]:
    return [
        json.loads(line[len("data: ") :])
        for line in sse_lines
        if line.startswith("data: ")
    ]


def test_midrun_events_are_present_in_sse_stream(
    monkeypatch: pytest.MonkeyPatch, mock_llm, tmp_path
) -> None:
    """① 中途事件回归：工作线程发的事件必须按序出现在 SSE 流（修复前必红）。

    设计文档 66 §3.5：Lead 推进动作（phase_start "Lead 编排: ..."）经事件桥转 task 事件。
    """
    from competitor_agent.memory import FourLayerMemory

    _patch_env(monkeypatch, mock_llm, EmitAPI, FourLayerMemory(tmp_path / "memory"))
    sid = "sess_sse_midrun"
    web_app._sessions[sid] = {"task": "分析 Cursor", "cancelled": False}
    EmitAPI.started.clear()

    async def _run() -> list[str]:
        sse_lines: list[str] = []
        async for line in web_app._event_generator(sid, "分析 Cursor"):
            sse_lines.append(line)
        return sse_lines

    try:
        sse_lines = asyncio.run(_run())
    finally:
        web_app._sessions.pop(sid, None)

    events = _collect(sse_lines)
    kinds = [e["event"] for e in events]
    messages = [e["message"] for e in events]
    assert "session_started" in kinds
    assert "report" in kinds, "正常报告完成事件缺失"
    # 中途 worker 线程发出的 Lead 推进动作 → task 事件按序到达 SSE
    mid = [m for m in messages if m.startswith("Lead 编排: 中途任务")]
    assert mid == ["Lead 编排: 中途任务0", "Lead 编排: 中途任务1", "Lead 编排: 中途任务2"], f"中途事件丢失: {mid}"
    # 顺序：中途任务须在 report 完成事件之前出现
    assert messages.index("Lead 编排: 中途任务2") < messages.index("报告生成完成，0 个维度")


def test_message_envelope_orders_text_delta(
    monkeypatch: pytest.MonkeyPatch, mock_llm, tmp_path
) -> None:
    """④ 设计文档 63 §3 消息信封：message.start → text_delta* → text.stop → message.stop。

    真实 LLM 叙述（stream_sink text_delta）归位 lead_id 气泡；Lead 推进动作转 task 事件
    （message_id 贯穿）；引擎内部 phase 不再收敛为正文（设计文档 66 §3.5）。
    """
    from competitor_agent.memory import FourLayerMemory

    _patch_env(monkeypatch, mock_llm, EmitAPI, FourLayerMemory(tmp_path / "memory"))
    sid = "sess_sse_envelope"
    web_app._sessions[sid] = {"task": "分析 Cursor", "cancelled": False}
    EmitAPI.started.clear()

    async def _run() -> list[str]:
        sse_lines: list[str] = []
        async for line in web_app._event_generator(sid, "分析 Cursor"):
            sse_lines.append(line)
        return sse_lines

    try:
        sse_lines = asyncio.run(_run())
    finally:
        web_app._sessions.pop(sid, None)

    events = _collect(sse_lines)
    kinds = [e["event"] for e in events]

    starts = [e for e in events if e["event"] == "message.start"]
    assert starts, "缺 message.start"
    lead_id = starts[0]["payload"]["message_id"]
    assert starts[0]["payload"]["source"] == "lead"

    # 真实 LLM 叙述 text_delta + task 事件 message_id 贯穿
    deltas = [e for e in events if e["event"] == "text_delta"]
    assert [d["payload"]["message_id"] for d in deltas] == [lead_id] * len(deltas)
    assert "正在分析" in [d["payload"]["delta"] for d in deltas]
    tasks = [e for e in events if e["event"] == "task"]
    assert tasks and tasks[0]["payload"]["message_id"] == lead_id

    # 顺序：message.start 最早 → text_delta → text.stop → message.stop
    assert kinds.index("message.start") < kinds.index("text_delta")
    text_stops = [e for e in events if e["event"] == "text.stop"]
    assert text_stops and text_stops[-1]["payload"]["final"] is True
    assert kinds.index("text.stop") < kinds.index("message.stop")
    assert "message.stop" in kinds


def test_drain_does_not_lose_events_at_completion(
    monkeypatch: pytest.MonkeyPatch, mock_llm, tmp_path
) -> None:
    """② drain 语义：分析完成瞬间队列中的残余事件不丢失。"""
    from competitor_agent.memory import FourLayerMemory

    class ManyEventsAPI(EmitAPI):
        def analyze(self, task, conversation_history=None, mode="team", session_id=None):
            type(self).started.set()
            for i in range(5):
                self.event_sink(
                    ProgressEvent(
                        event="discovery.candidate",
                        phase="strategic",
                        message=f"发现候选: c{i}",
                        payload={"candidate": f"c{i}"},
                    )
                )
            return CompetitorReport(
                competitor=Competitor(name="cursor"),
                dimension_results=[],
                terminal_state="success",
                markdown_report="# 完成",
            )

    _patch_env(monkeypatch, mock_llm, ManyEventsAPI, FourLayerMemory(tmp_path / "memory"))
    sid = "sess_sse_drain"
    web_app._sessions[sid] = {"task": "分析 Cursor", "cancelled": False}

    async def _run() -> list[str]:
        sse_lines: list[str] = []
        async for line in web_app._event_generator(sid, "分析 Cursor"):
            sse_lines.append(line)
        return sse_lines

    try:
        sse_lines = asyncio.run(_run())
    finally:
        web_app._sessions.pop(sid, None)

    events = _collect(sse_lines)
    messages = [e["message"] for e in events]
    batch = [m for m in messages if m.startswith("发现候选:")]
    assert batch == [f"发现候选: c{i}" for i in range(5)], f"完成瞬间事件丢失: {batch}"
    assert "report" in [e["event"] for e in events]


def test_cancel_response_within_bound(
    monkeypatch: pytest.MonkeyPatch, mock_llm, tmp_path
) -> None:
    """③ 取消响应 ≤ 上界：set_cancel 后 SSE 尽快收到 cancelled 事件（非忙轮询仍快）。"""
    from competitor_agent.memory import FourLayerMemory

    _patch_env(monkeypatch, mock_llm, SlowCancelAPI, FourLayerMemory(tmp_path / "memory"))
    sid = "sess_sse_cancel"
    web_app._sessions[sid] = {"task": "分析 Cursor", "cancelled": False}
    SlowCancelAPI.started.clear()

    async def _run() -> tuple[list[str], float]:
        sse_lines: list[str] = []

        async def consume() -> None:
            async for line in web_app._event_generator(sid, "分析 Cursor"):
                sse_lines.append(line)

        task = asyncio.create_task(consume())
        deadline = time.time() + 10
        while time.time() < deadline and not SlowCancelAPI.started.is_set():
            await asyncio.sleep(0.01)
        assert SlowCancelAPI.started.is_set(), "后台分析未启动"

        # 真实取消路由：设置会话标志 + 内部取消标志
        t0 = time.monotonic()
        await web_app.cancel(sid)
        await asyncio.wait_for(task, timeout=10)
        elapsed = time.monotonic() - t0
        return sse_lines, elapsed

    try:
        sse_lines, elapsed = asyncio.run(_run())
    finally:
        clear_cancel(sid)
        web_app._sessions.pop(sid, None)

    events = _collect(sse_lines)
    kinds = [e["event"] for e in events]
    assert "cancelled" in kinds, "SSE 未收到 cancelled 事件"
    assert "report" not in kinds
    assert elapsed < _CANCEL_RESPONSE_BOUND, f"取消响应过慢: {elapsed:.3f}s"


class TestNoPayloadReportDrop:
    """设计文档 70 §8.3 D3：web 侧丢弃无 payload 的 report 事件（防幽灵空报告）。"""

    def test_queue_sse_drops_no_payload_report(self) -> None:
        from competitor_agent.web_app import _queue_sse

        assert _queue_sse(
            ProgressEvent(event="report", phase="report", message="报告完成"), "lead"
        ) is None, "无 payload 的 report 事件应被丢弃"
        assert _queue_sse(
            ProgressEvent(
                event="report", phase="report", message="报告完成",
                payload={"competitor": "cursor"},
            ),
            "lead",
        ) is not None, "带 payload 的 report 事件应正常放行"

    def test_full_sse_stream_no_ghost_report(self, monkeypatch, mock_llm, tmp_path) -> None:
        """api 层发无 payload report 事件 + 返回正常单竞品报告 → SSE 只保留带 payload 的真实报告。"""
        from competitor_agent.domain_types.events import ProgressEvent

        class GhostReportAPI:
            def __init__(self, *args, **kwargs) -> None:
                self.event_sink = kwargs.get("event_sink")

            def run(self, task, *, session_id=None, history_messages=None):
                # 模拟 api.py:426 收尾的无 payload report 事件（CLI/MCP 报告完成信号）
                self.event_sink(ProgressEvent(event="report", phase="report", progress=1.0, message="报告生成完成"))
                return CompetitorReport(
                    competitor=Competitor(name="cursor"),
                    dimension_results=[],
                    terminal_state="success",
                    overall_confidence=0.8,
                    markdown_report="# Cursor 报告",
                )

        from competitor_agent.memory import FourLayerMemory

        _patch_env(monkeypatch, mock_llm, GhostReportAPI, FourLayerMemory(tmp_path / "memory"))
        sid = "sess_sse_ghost"
        web_app._sessions[sid] = {"task": "分析 Cursor", "cancelled": False}

        async def _run() -> list[str]:
            sse_lines: list[str] = []
            async for line in web_app._event_generator(sid, "分析 Cursor"):
                sse_lines.append(line)
            return sse_lines

        try:
            sse_lines = asyncio.run(_run())
        finally:
            web_app._sessions.pop(sid, None)

        reports = [e for e in _collect(sse_lines) if e["event"] == "report"]
        assert len(reports) == 1, f"应只剩带 payload 的真实报告事件: {reports}"
        assert reports[0]["payload"]["competitor"] == "cursor", "保留的是真实报告而非幽灵"

    def test_zero_candidate_comparison_archive_fallback(
        self, monkeypatch, mock_llm, tmp_path
    ) -> None:
        """设计文档 70 §8.1 D1a/D1b：零候选对比走完 SSE 不崩、归档名 "compare"、
        payload has_candidates==false（前端据此提示）。"""
        import competitor_agent.memory as mem_mod
        from competitor_agent.domain_types.report import ComparisonReport

        calls: dict[str, list] = {"names": []}

        class ZeroCandAPI:
            def __init__(self, *args, **kwargs) -> None:
                self.event_sink = kwargs.get("event_sink")

            def run(self, task, *, session_id=None, history_messages=None):
                return ComparisonReport(
                    competitors=[], reports=[],
                    markdown_report="# 零候选\n\n未收集到候选数据（候选委派超时/失败），对比矩阵为空，置信度 0% 为事实。",
                )

        def fake_archive(self, session, *a, **k) -> None:
            calls["names"].append(getattr(session, "competitor_name", None))

        monkeypatch.setattr(mem_mod.FourLayerMemory, "archive_session", fake_archive)
        from competitor_agent.memory import FourLayerMemory

        _patch_env(monkeypatch, mock_llm, ZeroCandAPI, FourLayerMemory(tmp_path / "memory"))
        monkeypatch.setattr(web_app, "save_report_download", lambda *a, **k: tmp_path / "dl.md")
        sid = "sess_sse_zero"
        web_app._sessions[sid] = {"task": "对比 Cursor vs Windsurf", "cancelled": False}

        async def _run() -> list[str]:
            sse_lines: list[str] = []
            async for line in web_app._event_generator(sid, "对比 Cursor vs Windsurf"):
                sse_lines.append(line)
            return sse_lines

        try:
            sse_lines = asyncio.run(_run())
        finally:
            web_app._sessions.pop(sid, None)

        events = _collect(sse_lines)
        kinds = [e["event"] for e in events]
        # 零候选不再触发"系统分析异常"
        assert "error" not in kinds, f"零候选对比不应报错: {[e.get('message') for e in events]}"
        report_ev = [e for e in events if e["event"] == "report"]
        assert report_ev, "应有 report 事件（空报告留痕）"
        assert report_ev[0]["payload"]["has_candidates"] is False
        assert report_ev[0]["payload"]["competitor"] == "compare"
        assert calls["names"] == ["compare"], f"归档 competitor_name 应兜底 'compare': {calls['names']}"


class TestStaticServing:
    """设计文档 50 §7.3：static 抽离后打包可读性回归——index/静态资源可经资源定位读取。"""

    def test_index_serves_frontend(self) -> None:
        import asyncio

        html = asyncio.run(web_app.index())
        # 设计文档 63：对话页（消息区 + 底部发送框），无开始分析按钮/进度条
        assert 'id="messages"' in html
        assert 'id="send-btn"' in html
        assert 'id="input"' in html
        assert 'id="new-btn"' in html
        assert '/static/style.css' in html
        assert '/static/app.js' in html
        assert '/static/vendor/marked.min.js' in html
        assert '/static/vendor/dompurify.min.js' in html

    def test_static_dir_is_readable_via_resources(self) -> None:
        for rel in ("index.html", "app.js", "style.css", "vendor/marked.min.js", "vendor/dompurify.min.js"):
            assert web_app._STATIC_DIR.joinpath(rel).is_file(), f"static 资源缺失: {rel}"

    def test_static_endpoints_serve_200(self) -> None:
        from fastapi.testclient import TestClient

        with TestClient(web_app.app) as client:
            assert client.get("/").status_code == 200
            for path in ("/static/style.css", "/static/app.js", "/static/vendor/marked.min.js"):
                resp = client.get(path)
                assert resp.status_code == 200, f"{path} 未命中静态挂载"
                assert resp.headers["content-type"].startswith("text/") or "javascript" in resp.headers["content-type"]