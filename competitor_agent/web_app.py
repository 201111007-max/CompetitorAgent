"""Web 应用 — FastAPI + SSE 可视化竞品分析进度

启动：
    pip install -e ".[web]"
    python -m competitor_agent.web_app --port 8000
    打开 http://localhost:8000

SSE 端点：
    GET /api/analyze?task=分析%20Cursor  → 流式返回 ProgressEvent
    GET /api/history                     → 历史报告列表
    GET /api/history/{competitor}        → 某竞品历史
    POST /api/cancel/{session_id}        → 取消运行中会话
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from competitor_agent import CompetitorAnalysisAPI
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.domain_types.report import CompetitorReport
from competitor_agent.interfaces.context import AnalysisSession
from competitor_agent.memory.four_layer_memory import FourLayerMemory
from competitor_agent.secret_vault import get_data_dir

logger = logging.getLogger("competitor_agent.web_app")

# ── 全局状态 ──────────────────────────────────────────────────────────────
_sessions: dict[str, dict[str, Any]] = {}  # session_id → {task, cancel_flag, ...}
_memory: FourLayerMemory | None = None


def _get_memory() -> FourLayerMemory:
    global _memory
    if _memory is None:
        _memory = FourLayerMemory(data_dir=get_data_dir() / "memory")
    return _memory


# ── SSE 辅助 ──────────────────────────────────────────────────────────────

async def _event_generator(
    session_id: str,
    task: str,
) -> AsyncIterator[str]:
    """SSE 事件生成器：逐条 yield ProgressEvent"""
    CompetitorAnalysisAPI(
        use_llm=False,
        memory=_get_memory(),
        event_sink=lambda e: None,  # 事件通过 yield 推送，不依赖 callback
    )

    events_queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()

    def _on_event(event: ProgressEvent) -> None:
        """将事件推入 asyncio 队列"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(lambda: events_queue.put_nowait(event))
        except RuntimeError:
            pass

    api_with_sink = CompetitorAnalysisAPI(
        use_llm=False,
        memory=_get_memory(),
        event_sink=_on_event,
    )

    # 启动后台分析任务
    async def _run_analysis() -> CompetitorReport:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, api_with_sink.analyze, task)

    analysis_task = asyncio.create_task(_run_analysis())

    try:
        # 先发送 session_started 事件
        yield ProgressEvent(
            event="session_started",
            phase="init",
            message=f"会话 {session_id} 已启动",
            payload={"session_id": session_id},
        ).to_sse()

        # 持续消费事件队列直到分析完成
        while True:
            done = analysis_task.done()
            # 消费队列中所有已有事件
            while not events_queue.empty():
                event = events_queue.get_nowait()
                yield event.to_sse()

            if done:
                break

            # 检查取消标志
            if _sessions.get(session_id, {}).get("cancelled", False):
                logger.info("会话 %s 被取消", session_id)
                yield ProgressEvent(
                    event="cancelled",
                    phase="report",
                    message="分析已被用户取消",
                ).to_sse()
                analysis_task.cancel()
                return

            await asyncio.sleep(0.05)

        # 分析完成，获取报告
        report = analysis_task.result()
        yield ProgressEvent(
            event="report",
            phase="report",
            progress=1.0,
            message=f"报告生成完成，{len(report.dimension_results)} 个维度",
            payload={
                "competitor": report.competitor.name,
                "terminal_state": report.terminal_state,
                "overall_confidence": report.overall_confidence,
                "dimensions": [r.dimension for r in report.dimension_results],
            },
        ).to_sse()

        # 归档会话
        _get_memory().archive_session(
            AnalysisSession(
                task=task,
                competitor_name=report.competitor.name,
                session_id=session_id,
                raw={
                    "terminal_state": report.terminal_state,
                    "dimension_count": len(report.dimension_results),
                    "markdown_report": report.markdown_report,
                },
            )
        )

    except asyncio.CancelledError:
        yield ProgressEvent(event="cancelled", phase="report", message="分析已取消").to_sse()
    except Exception as exc:
        logger.exception("分析异常")
        yield ProgressEvent(
            event="error",
            phase="error",
            message=f"分析异常: {exc}",
        ).to_sse()


# ── FastAPI 应用 ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("竞品分析 Web 服务启动")
    yield
    logger.info("竞品分析 Web 服务关闭")


app = FastAPI(title="Competitor Intelligence Agent", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """简易前端页面"""
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>竞品分析 Agent</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
#log { background: #f5f5f5; padding: 12px; border-radius: 6px; min-height: 200px; font-size: 14px; line-height: 1.6; }
.event { margin: 4px 0; padding: 4px 8px; border-left: 3px solid #ccc; }
.event.phase_start { border-color: #2196F3; }
.event.phase_complete { border-color: #4CAF50; }
.event.report { border-color: #FF9800; font-weight: bold; }
.event.error { border-color: #f44336; color: #f44336; }
.event.cancelled { border-color: #9E9E9E; color: #9E9E9E; }
input, button { padding: 8px 16px; font-size: 16px; }
input { width: 400px; }
button { cursor: pointer; background: #2196F3; color: white; border: none; border-radius: 4px; }
button:hover { background: #1976D2; }
button:disabled { background: #ccc; }
#cancel-btn { background: #f44336; }
#cancel-btn:hover { background: #d32f2f; }
</style>
</head>
<body>
<h1>竞品分析 Agent</h1>
<div>
    <input id="task" type="text" placeholder="输入竞品名称，如 Cursor" value="Cursor" />
    <button id="start-btn" onclick="startAnalysis()">开始分析</button>
    <button id="cancel-btn" onclick="cancelAnalysis()" disabled>取消</button>
</div>
<hr/>
<div id="log">等待输入...</div>
<script>
let eventSource = null;
let sessionId = null;

function addLog(event, message) {
    const log = document.getElementById('log');
    const div = document.createElement('div');
    div.className = 'event ' + (event || '');
    div.textContent = '[' + new Date().toLocaleTimeString() + '] ' + message;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
}

function startAnalysis() {
    const task = document.getElementById('task').value.trim();
    if (!task) return;
    sessionId = 'sess_' + Date.now();
    document.getElementById('log').innerHTML = '';
    document.getElementById('start-btn').disabled = true;
    document.getElementById('cancel-btn').disabled = false;

    eventSource = new EventSource('/api/analyze?task=' + encodeURIComponent(task) + '&session_id=' + sessionId);
    eventSource.onmessage = function(e) {
        const data = JSON.parse(e.data);
        addLog(data.event, data.message || (data.phase || '') + ' [' + (data.progress * 100).toFixed(0) + '%]');
        if (data.event === 'report' || data.event === 'error' || data.event === 'cancelled') {
            eventSource.close();
            document.getElementById('start-btn').disabled = false;
            document.getElementById('cancel-btn').disabled = true;
        }
    };
    eventSource.onerror = function() {
        addLog('error', '连接断开');
        eventSource.close();
        document.getElementById('start-btn').disabled = false;
        document.getElementById('cancel-btn').disabled = true;
    };
}

function cancelAnalysis() {
    if (sessionId) {
        fetch('/api/cancel/' + sessionId, { method: 'POST' });
        addLog('cancelled', '正在取消...');
    }
}
</script>
</body>
</html>"""


@app.get("/api/analyze")
async def analyze(
    request: Request,
    task: str = Query(..., description="分析任务，如'分析 Cursor'"),
    session_id: str = Query(default="", description="会话 ID（可选）"),
) -> AsyncIterator[str]:
    """SSE 流式分析"""
    sid = session_id or f"sess_{uuid.uuid4().hex[:8]}"
    _sessions[sid] = {"task": task, "cancelled": False}

    async for event in _event_generator(sid, task):
        if await request.is_disconnected():
            _sessions[sid]["cancelled"] = True
            break
        yield event

    _sessions.pop(sid, None)


@app.post("/api/cancel/{session_id}")
async def cancel(session_id: str) -> JSONResponse:
    """取消运行中的分析会话"""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    _sessions[session_id]["cancelled"] = True
    return JSONResponse({"status": "cancelled", "session_id": session_id})


@app.get("/api/history")
async def history() -> JSONResponse:
    """查询所有竞品的历史分析记录"""
    sessions = _get_memory().recent_sessions()
    return JSONResponse([
        {
            "session_id": s.session_id,
            "competitor": s.competitor_name,
            "task": s.task,
            "created_at": s.created_at,
        }
        for s in sessions
    ])


@app.get("/api/history/{competitor}")
async def history_by_competitor(competitor: str) -> JSONResponse:
    """查询指定竞品的历史分析记录"""
    sessions = _get_memory()._sessions.retrieve(competitor)
    return JSONResponse([
        {
            "session_id": s.session_id,
            "task": s.task,
            "created_at": s.created_at,
        }
        for s in sessions
    ])


@app.get("/api/status/{session_id}")
async def status(session_id: str) -> JSONResponse:
    """查询会话状态"""
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在或已结束")
    return JSONResponse({
        "session_id": session_id,
        "task": session.get("task", ""),
        "cancelled": session.get("cancelled", False),
    })


def main() -> None:
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="竞品分析 Agent Web 服务")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="监听地址")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
