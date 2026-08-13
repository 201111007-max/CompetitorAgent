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
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from competitor_agent import CompetitorAnalysisAPI
from competitor_agent.config.loader import AppConfig, load_config
from competitor_agent.core.checkpoint import set_cancel
from competitor_agent.core.report_archiver import report_file_path, save_report_markdown
from competitor_agent.core.task_parser import ResolutionDecision, parse_task
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.domain_types.report import (
    CancelledResult,
    ComparisonReport,
    CompetitorReport,
)
from competitor_agent.interfaces.context import AnalysisSession
from competitor_agent.llm.client import LLMClient
from competitor_agent.memory.four_layer_memory import FourLayerMemory
from competitor_agent.observability.logger import (
    close_session_log,
    read_session_log,
    setup_logging,
)
from competitor_agent.secret_vault import get_data_dir

logger = logging.getLogger("competitor_agent.web_app")

# ── 全局状态 ──────────────────────────────────────────────────────────────
_sessions: dict[str, dict[str, Any]] = {}  # session_id → {task, cancel_flag, ...}
_memory: FourLayerMemory | None = None
_config: AppConfig = load_config()


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
        llm=LLMClient(model=_config.model, base_url=_config.api_base_url),
        use_llm=True,
        memory=_get_memory(),
        event_sink=_on_event,
        config=load_config(),
    )

    # 启动后台分析任务（按 resolution 路由：DISCOVERY→发现对比 / COMPARE→N 向对比 / 其余→单竞品）
    # 路由用规则解析（不触发真实 LLM/网络；实际分析在 api.discover/analyze 内部再走 LLM）
    async def _run_analysis() -> CompetitorReport | ComparisonReport:
        loop = asyncio.get_running_loop()
        parsed = parse_task(task, llm=None, use_llm=False)
        if parsed.resolution == ResolutionDecision.DISCOVERY:
            return await loop.run_in_executor(None, api_with_sink.discover, task)
        if parsed.is_compare and len(parsed.competitors) >= 2:
            return await loop.run_in_executor(None, api_with_sink.compare, *parsed.competitors)
        return await loop.run_in_executor(None, api_with_sink.analyze, task, None, "team", session_id)

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
                # 关键修复：内部取消标志与 web sid 打通，协作式取消真正中断运行中的分析
                api_with_sink.cancel(session_id)
                yield ProgressEvent(
                    event="cancelled",
                    phase="report",
                    message="分析已被用户取消，返回部分结果",
                ).to_sse()
                # 取消 asyncio 包装任务（避免 pending 警告）；运行中的线程由协作式取消自行尽快退出
                analysis_task.cancel()
                return

            await asyncio.sleep(0.05)

        # 分析完成，获取报告
        report = analysis_task.result()
        if isinstance(report, CancelledResult):
            yield ProgressEvent(
                event="cancelled",
                phase="report",
                message=f"分析已取消，返回 {len(report.dimension_results)} 个已完成维度",
                payload={
                    "competitor": report.competitor.name,
                    "terminal_state": "cancelled",
                },
            ).to_sse()
            return

        if isinstance(report, ComparisonReport):
            # 多竞品对比/发现：聚合维度 + 整份矩阵 Markdown
            all_dims = [
                r.dimension for rep in report.reports for r in rep.dimension_results
            ]
            yield ProgressEvent(
                event="report",
                phase="report",
                progress=1.0,
                message=f"对比报告生成完成，{len(report.reports)} 个竞品 / {len(set(all_dims))} 个维度",
                payload={
                    "competitor": " / ".join(c.name for c in report.competitors),
                    "terminal_state": "compare",
                    "overall_confidence": max(
                        (r.overall_confidence for r in report.reports), default=0.0
                    ),
                    "dimensions": list(dict.fromkeys(all_dims)),
                    "markdown_report": report.markdown_report,
                    "session_id": session_id,
                    "is_comparison": True,
                },
            ).to_sse()
            # 自动落盘对比报告
            save_report_markdown(report)
            # 归档会话
            _get_memory().archive_session(
                AnalysisSession(
                    task=task,
                    competitor_name=" / ".join(c.name for c in report.competitors),
                    session_id=session_id,
                    raw={
                        "markdown_report": report.markdown_report,
                        "terminal_state": "compare",
                        "dimension_count": len(set(all_dims)),
                        "competitor_name": " / ".join(c.name for c in report.competitors),
                        "created_at": report.created_at,
                    },
                )
            )
            return

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
                "markdown_report": report.markdown_report,
                "session_id": session_id,
            },
        ).to_sse()

        # 自动落盘 reports/competitor/<竞品>.md（导出/下载用）
        save_report_markdown(report)

        # 归档会话（统一 raw schema）
        _get_memory().archive_session(
            AnalysisSession(
                task=task,
                competitor_name=report.competitor.name,
                session_id=session_id,
                raw={
                    "markdown_report": report.markdown_report,
                    "terminal_state": report.terminal_state,
                    "dimension_count": len(report.dimension_results),
                    "competitor_name": report.competitor.name,
                    "created_at": report.created_at,
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
    allow_origins=_config.security.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_auth(
    request: Request,
    token: str = Query(default="", description="API Token（可选，也可用 Authorization: Bearer）"),
) -> None:
    """API Token 认证依赖：未配置 token 时放行（本地开发），配置后校验 Bearer 或 ?token=。"""
    expected = _config.security.auth_token
    if not expected:
        return
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        provided = header[len("Bearer ") :]
    else:
        provided = token
    if provided != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


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
#report { border: 1px solid #ddd; border-radius: 6px; padding: 12px; margin-top: 12px; white-space: pre-wrap; font-size: 13px; display: none; }
#report.visible { display: block; }
#candidates { margin-top: 12px; font-size: 13px; color: #1565C0; display: none; }
#candidates.visible { display: block; }
.matrix-box { margin-top: 12px; }
.matrix-box table { border-collapse: collapse; width: 100%; font-size: 13px; }
.matrix-box th, .matrix-box td { border: 1px solid #ddd; padding: 6px 8px; text-align: left; }
.matrix-box th { background: #f0f4f8; }
.report-toolbar { margin-top: 12px; }
.report-toolbar button { margin-right: 8px; }
#session-log { background: #111; color: #0f0; padding: 12px; border-radius: 6px; font-size: 12px; line-height: 1.5; height: 160px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }
details { margin-top: 12px; }
</style>
</head>
<body>
<h1>竞品分析 Agent</h1>
<div>
    <input id="task" type="text" placeholder="输入竞品名称，如 Cursor（多竞品用逗号分隔，普查任务如“所有 AI coding agent”将自动发现）" value="Cursor" />
    <button id="start-btn" onclick="startAnalysis()">开始分析</button>
    <button id="cancel-btn" onclick="cancelAnalysis()" disabled>取消</button>
</div>
<hr/>
<div id="log">等待输入...</div>
<div id="candidates"><strong>发现候选:</strong> <span id="candidate-list"></span></div>
<div id="report-toolbar" class="report-toolbar" style="display:none;">
    <button onclick="copyReport()">复制 Markdown</button>
    <button id="download-btn" onclick="downloadReport()">下载 .md</button>
</div>
<div id="matrix" class="matrix-box" style="display:none;"></div>
<div id="report"></div>
<details>
    <summary>会话日志</summary>
    <div id="session-log">（分析开始后实时显示）</div>
</details>
<script>
let eventSource = null;
let logSource = null;
let sessionId = null;
let discoveredCandidates = [];
let lastReport = null;

function addLog(event, message) {
    const log = document.getElementById('log');
    const div = document.createElement('div');
    div.className = 'event ' + (event || '');
    div.textContent = '[' + new Date().toLocaleTimeString() + '] ' + message;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
}

function openLogStream() {
    if (!sessionId) return;
    document.getElementById('session-log').textContent = '';
    logSource = new EventSource('/api/logs/stream/' + sessionId);
    logSource.onmessage = function(e) {
        const data = JSON.parse(e.data);
        if (data.event === 'log_end') { logSource.close(); return; }
        const line = '[' + (data.ts || '') + '] ' + (data.event || '') + ' ' + (data.message || JSON.stringify(data));
        const box = document.getElementById('session-log');
        box.textContent += line + '\n';
        box.scrollTop = box.scrollHeight;
    };
    logSource.onerror = function() { if (logSource) logSource.close(); };
}

function closeLogStream() { if (logSource) { logSource.close(); logSource = null; } }

function startAnalysis() {
    const task = document.getElementById('task').value.trim();
    if (!task) return;
    sessionId = 'sess_' + Date.now();
    document.getElementById('log').innerHTML = '';
    clearCandidates();
    clearReport();
    document.getElementById('start-btn').disabled = true;
    document.getElementById('cancel-btn').disabled = false;
    openLogStream();

    eventSource = new EventSource('/api/analyze?task=' + encodeURIComponent(task) + '&session_id=' + sessionId);
    eventSource.onmessage = function(e) {
        const data = JSON.parse(e.data);
        addLog(data.event, data.message || (data.phase || '') + ' [' + (data.progress * 100).toFixed(0) + '%]');
        if (data.event === 'discovery.candidate' && data.payload && data.payload.candidate) {
            addCandidate(data.payload.candidate);
        }
        if (data.event === 'report') {
            renderReport(data.payload);
        }
        if (data.event === 'report' || data.event === 'error' || data.event === 'cancelled') {
            eventSource.close();
            closeLogStream();
            document.getElementById('start-btn').disabled = false;
            document.getElementById('cancel-btn').disabled = true;
            if (data.event !== 'report') clearReport();
        }
    };
    eventSource.onerror = function() {
        addLog('error', '连接断开');
        eventSource.close();
        closeLogStream();
        document.getElementById('start-btn').disabled = false;
        document.getElementById('cancel-btn').disabled = true;
        clearReport();
    };
}

function addCandidate(name) {
    if (discoveredCandidates.indexOf(name) === -1) {
        discoveredCandidates.push(name);
        document.getElementById('candidates').classList.add('visible');
        document.getElementById('candidate-list').textContent = discoveredCandidates.join(', ');
    }
}

function clearCandidates() {
    discoveredCandidates = [];
    document.getElementById('candidates').classList.remove('visible');
    document.getElementById('candidate-list').textContent = '';
}

function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}

function renderMatrix(md) {
    const matrix = document.getElementById('matrix');
    if (!md || !md.includes('品类格局矩阵')) {
        matrix.innerHTML = '';
        matrix.style.display = 'none';
        return;
    }
    const rows = md.split('\n')
        .filter(l => l.trim().startsWith('|'))
        .map(l => l.trim().replace(/^[|]/, '').replace(/[|]$/, '').split('|').map(c => c.trim()))
        .filter(row => !row.every(c => /^:?-+:?$/.test(c)));  // 跳过 --- 分隔行
    const html = rows.map((row, i) => '<tr>' + row.map(c =>
        '<' + (i === 0 ? 'th' : 'td') + '>' + escapeHtml(c) + '</' + (i === 0 ? 'th' : 'td') + '>'
    ).join('') + '</tr>').join('');
    matrix.innerHTML = '<table>' + html + '</table>';
    matrix.style.display = 'block';
}

function renderReport(payload) {
    const report = document.getElementById('report');
    if (!payload || !payload.markdown_report) return;
    lastReport = payload;
    report.textContent = payload.markdown_report;  // 服务端已转义，直接文本注入（防 XSS）
    report.classList.add('visible');
    document.getElementById('report-toolbar').style.display = 'block';
    const dl = document.getElementById('download-btn');
    dl.disabled = !payload.competitor;
    renderMatrix(payload.markdown_report);  // 对比报告额外渲染品类格局矩阵表格
}

function copyReport() {
    if (!lastReport || !lastReport.markdown_report) return;
    navigator.clipboard.writeText(lastReport.markdown_report)
        .then(() => addLog('report', '已复制 Markdown'))
        .catch(() => addLog('error', '复制失败'));
}

function downloadReport() {
    if (!lastReport || !lastReport.competitor) return;
    window.location.href = '/api/reports/' + encodeURIComponent(lastReport.competitor) + '/download';
}

function clearReport() {
    lastReport = null;
    const report = document.getElementById('report');
    report.textContent = '';
    report.classList.remove('visible');
    document.getElementById('report-toolbar').style.display = 'none';
    const matrix = document.getElementById('matrix');
    matrix.innerHTML = '';
    matrix.style.display = 'none';
    clearCandidates();
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
    _: None = Depends(require_auth),
    task: str = Query(..., description="分析任务，如'分析 Cursor'"),
    session_id: str = Query(default="", description="会话 ID（可选）"),
) -> StreamingResponse:
    """SSE 流式分析"""
    sid = session_id or f"sess_{uuid.uuid4().hex[:8]}"
    _sessions[sid] = {"task": task, "cancelled": False}

    async def _stream() -> AsyncIterator[str]:
        try:
            async for event in _event_generator(sid, task):
                if await request.is_disconnected():
                    _sessions[sid]["cancelled"] = True
                    set_cancel(sid)  # 断连也触发协作式取消，停止后台分析
                    break
                yield event
        finally:
            _sessions.pop(sid, None)

    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.post("/api/cancel/{session_id}")
async def cancel(session_id: str, _: None = Depends(require_auth)) -> JSONResponse:
    """取消运行中的分析会话"""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    _sessions[session_id]["cancelled"] = True
    # 内部取消标志与 web sid 打通：运行中的 analyze 轮询感知后协作式终止
    set_cancel(session_id)
    return JSONResponse({"status": "cancelled", "session_id": session_id})


@app.get("/api/history")
async def history(_: None = Depends(require_auth)) -> JSONResponse:
    """查询所有竞品的历史分析记录"""
    sessions = _get_memory().recent_sessions()
    return JSONResponse(
        [
            {
                "session_id": s.session_id,
                "competitor": s.competitor_name,
                "task": s.task,
                "created_at": s.created_at,
            }
            for s in sessions
        ]
    )


@app.get("/api/history/{competitor}")
async def history_by_competitor(competitor: str, _: None = Depends(require_auth)) -> JSONResponse:
    """查询指定竞品的历史分析记录"""
    sessions = _get_memory().list_sessions(competitor)
    return JSONResponse(
        [
            {
                "session_id": s.session_id,
                "task": s.task,
                "created_at": s.created_at,
            }
            for s in sessions
        ]
    )


@app.get("/api/status/{session_id}")
async def status(session_id: str, _: None = Depends(require_auth)) -> JSONResponse:
    """查询会话状态"""
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在或已结束")
    return JSONResponse(
        {
            "session_id": session_id,
            "task": session.get("task", ""),
            "cancelled": session.get("cancelled", False),
        }
    )


@app.get("/api/logs/{session_id}")
async def logs(
    session_id: str,
    _: None = Depends(require_auth),
    tail: int = Query(default=500, ge=1, le=10000),
) -> JSONResponse:
    """返回该次分析的会话日志（logs/<sid>.log，tail 限定最近 N 行）"""
    lines = read_session_log(session_id, tail=tail)
    return JSONResponse({"session_id": session_id, "count": len(lines), "lines": lines})


@app.get("/api/logs/stream/{session_id}")
async def logs_stream(
    request: Request,
    session_id: str,
    _: None = Depends(require_auth),
) -> StreamingResponse:
    """SSE 推送会话日志尾部追加（配合前端实时查看）"""

    async def _stream() -> AsyncIterator[str]:
        sent = 0
        last_activity = time.monotonic()
        while True:
            if await request.is_disconnected():
                break
            lines = read_session_log(session_id)
            if len(lines) > sent:
                for line in lines[sent:]:
                    yield f"data: {json.dumps(line, ensure_ascii=False)}\n\n"
                sent = len(lines)
                last_activity = time.monotonic()
            # 会话结束（_sessions 中已移除）且已推完 → 收尾
            if session_id not in _sessions and len(lines) == sent:
                yield f"data: {json.dumps({'event': 'log_end', 'session_id': session_id})}\n\n"
                break
            if time.monotonic() - last_activity > 300:
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.get("/api/reports/{competitor}")
async def report_file(
    competitor: str,
    _: None = Depends(require_auth),
) -> FileResponse:
    """返回落盘的报告文件 reports/competitor/<competitor>.md；不存在返回 404。"""
    path = report_file_path(competitor)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"报告不存在: {competitor}")
    return FileResponse(path, media_type="text/markdown; charset=utf-8")


@app.get("/api/reports/{competitor}/download")
async def report_download(
    competitor: str,
    _: None = Depends(require_auth),
) -> FileResponse:
    """以 Content-Disposition: attachment 下载报告（触发浏览器下载）。"""
    path = report_file_path(competitor)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"报告不存在: {competitor}")
    return FileResponse(path, media_type="text/markdown; charset=utf-8", filename=f"{competitor}.md")


def main() -> None:
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="竞品分析 Agent Web 服务")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="监听地址")
    args = parser.parse_args()

    setup_logging(level=_config.observability.log_level, log_dir=get_data_dir() / "logs")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
