"""问题 4 Web 端到端：取消后 SSE 正常结束且返回取消状态

用 SlowCancelAPI 替换 Web 内真实 API：分析运行中等待取消标志，
直接驱动生产使用的 `_event_generator` + 真实 `/api/cancel/{sid}` 路由逻辑，
验证 cancel → set_cancel → 协作式终止 → SSE 收到 cancelled 事件并正常收尾。
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
from competitor_agent.domain_types.report import CancelledResult


class SlowCancelAPI:
    """模拟运行中的分析：一旦感知取消即返回 CancelledResult"""

    started = threading.Event()

    def __init__(self, *args, **kwargs) -> None:
        pass

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

    def cancel(self, session_id: str) -> None:
        set_cancel(session_id)


@pytest.mark.asyncio
async def test_web_cancel_ends_sse_with_cancelled_event(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_app, "CompetitorAnalysisAPI", SlowCancelAPI)
    sid = "sess_e2e_gen"
    web_app._sessions[sid] = {"task": "分析 Cursor", "cancelled": False}
    SlowCancelAPI.started.clear()

    sse_lines: list[str] = []

    async def consume() -> None:
        async for line in web_app._event_generator(sid, "分析 Cursor"):
            sse_lines.append(line)

    task = asyncio.create_task(consume())
    try:
        deadline = time.time() + 10
        while time.time() < deadline and not SlowCancelAPI.started.is_set():
            await asyncio.sleep(0.01)
        assert SlowCancelAPI.started.is_set(), "后台分析未启动"

        # 真实取消路由逻辑：设置会话标志 + 内部取消标志
        await web_app.cancel(sid)

        await asyncio.wait_for(task, timeout=15)

        events = [
            json.loads(line[len("data: "):])
            for line in sse_lines
            if line.startswith("data: ")
        ]
        kinds = [e["event"] for e in events]
        assert any("session_started" in k for k in kinds), "SSE 未收到 session_started 事件"
        assert "cancelled" in kinds, "SSE 未收到 cancelled 事件（取消未真正中断分析）"
        assert "report" not in kinds, "取消后不应再推送正常 report 完成事件"
    finally:
        clear_cancel(sid)
        web_app._sessions.pop(sid, None)