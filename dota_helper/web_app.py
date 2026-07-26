"""Dota Helper Web 入口

同时暴露赛后复盘端点（PostMatchReviewAPI）与 ReAct Agent Chat 端点。
Chat 后端在阶段 10 之前由 MockReActAgent 填充，前端按真实事件契约实现。
"""
import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from dota_helper import PostMatchReviewAPI, create_default_api
from dota_helper.domain_types.events import ProgressEvent
from dota_helper.observability.logger import get_logger

logger = get_logger("web_app")

# 项目根目录与静态资源路径
PACKAGE_ROOT = Path(__file__).parent
WARD_DIR = PACKAGE_ROOT / "ward_analysis"
FRONTEND_DIR = PACKAGE_ROOT / "frontend"
INDEX_HTML = FRONTEND_DIR / "index.html"

# 内存聊天会话存储（阶段 10 替换为持久化存储）
_chat_sessions: Dict[str, Dict[str, Any]] = {}
_chat_history: List[Dict[str, Any]] = []


class MockReActAgent:
    """阶段 7 占位用 ReAct Agent

    按阶段 10 设计的事件契约产出 session/thought/action/observation/final，
    支持 ward_html 路径以验证 WardIframe 组件。
    """

    def __init__(self) -> None:
        """初始化 Mock Agent"""
        self._closed = False

    async def run_stream(
        self,
        message: str,
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """模拟 ReAct Agent 流式输出

        Args:
            message: 用户输入
            session_id: 已有会话 ID（可选）

        Yields:
            Dict[str, Any]: ChatEvent 字典
        """
        if self._closed:
            return

        sid = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        cid = f"conv_{uuid.uuid4().hex[:12]}"
        lower = message.lower()
        is_ward = any(k in lower for k in ("ward", "眼位", "视野", "vision"))

        # session 事件
        yield {
            "type": "session",
            "session_id": sid,
            "conversation_id": cid,
        }
        await asyncio.sleep(0.05)

        # thought
        yield {
            "type": "thought",
            "session_id": sid,
            "conversation_id": cid,
            "content": f"正在分析用户问题：{message[:50]}",
        }
        await asyncio.sleep(0.05)

        # action
        action_input: Dict[str, Any] = {"query": message[:50]}
        if is_ward:
            action_input["tool"] = "analyze_ward"
            action_input["match_id"] = "demo"
        yield {
            "type": "action",
            "session_id": sid,
            "conversation_id": cid,
            "content": "调用分析工具",
            "input": action_input,
        }
        await asyncio.sleep(0.05)

        # observation
        observation_content = "已获取相关数据。"
        if is_ward:
            observation_content = "已生成眼位热力图数据。"
        yield {
            "type": "observation",
            "session_id": sid,
            "conversation_id": cid,
            "content": observation_content,
        }
        await asyncio.sleep(0.05)

        # final
        final_payload: Dict[str, Any] = {
            "type": "final",
            "session_id": sid,
            "conversation_id": cid,
            "content": f"这是关于「{message[:30]}」的模拟回答。",
        }
        if is_ward:
            final_payload["ward_html"] = "/ward_analysis/demo.html"
        yield final_payload

        # 持久化会话
        await self._save_session(sid, cid, message, final_payload["content"])

    async def _save_session(
        self,
        session_id: str,
        conversation_id: str,
        message: str,
        answer: str,
    ) -> None:
        """将会话保存到内存存储

        Args:
            session_id: 会话 ID
            conversation_id: 对话 ID
            message: 用户消息
            answer: Agent 回答
        """
        now = time.time()
        if session_id not in _chat_sessions:
            _chat_sessions[session_id] = {
                "session_id": session_id,
                "title": message[:20] or "新会话",
                "created_at": now,
                "updated_at": now,
                "messages": [],
            }
            _chat_history.append({
                "session_id": session_id,
                "title": _chat_sessions[session_id]["title"],
                "updated_at": now,
            })
        session = _chat_sessions[session_id]
        session["messages"].append({
            "conversation_id": conversation_id,
            "role": "user",
            "content": message,
            "created_at": now,
        })
        session["messages"].append({
            "conversation_id": conversation_id,
            "role": "agent",
            "content": answer,
            "created_at": now,
        })
        session["updated_at"] = now
        # 同步更新历史列表中的时间
        for item in _chat_history:
            if item["session_id"] == session_id:
                item["updated_at"] = now
                item["title"] = session["title"]


# 全局状态
review_api: Optional[PostMatchReviewAPI] = None
chat_agent: MockReActAgent = MockReActAgent()


def _ensure_directories() -> None:
    """确保运行时目录存在"""
    WARD_DIR.mkdir(parents=True, exist_ok=True)
    FRONTEND_DIR.mkdir(parents=True, exist_ok=True)


def _create_ward_demo() -> None:
    """创建示例 ward HTML，供 Mock Agent 引用"""
    demo_path = WARD_DIR / "demo.html"
    if demo_path.exists():
        return
    demo_html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Ward Analysis Demo</title>
    <style>
        body { margin: 0; background: #1a1a2e; color: #eee; font-family: sans-serif; }
        .map { width: 512px; height: 512px; margin: 40px auto; background: #16213e; border-radius: 8px; position: relative; }
        .ward { position: absolute; width: 16px; height: 16px; border-radius: 50%; background: #0f3460; border: 2px solid #e94560; }
    </style>
</head>
<body>
    <h2 style="text-align:center">眼位分析示例</h2>
    <div class="map">
        <div class="ward" style="left:120px;top:140px"></div>
        <div class="ward" style="left:300px;top:220px"></div>
        <div class="ward" style="left:420px;top:380px"></div>
    </div>
</body>
</html>"""
    try:
        demo_path.write_text(demo_html, encoding="utf-8")
    except Exception as e:
        logger.warning("创建 ward demo.html 失败: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理

    Args:
        app: FastAPI 应用实例
    """
    global review_api
    _ensure_directories()
    _create_ward_demo()
    if review_api is None:
        logger.info("正在初始化 PostMatchReviewAPI...")
        review_api = create_default_api()
        logger.info("PostMatchReviewAPI 初始化完成")
    else:
        logger.info("PostMatchReviewAPI 已由外部注入，跳过默认初始化")
    yield
    logger.info("Web 应用关闭")


app = FastAPI(
    title="Dota Helper",
    description="Dota 2 赛后复盘与 ReAct Agent Chat",
    lifespan=lifespan,
)

# 开发环境 CORS
_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 挂载 ward_analysis 静态目录
if WARD_DIR.exists():
    app.mount("/ward_analysis", StaticFiles(directory=str(WARD_DIR)), name="ward_analysis")



# ── 复盘 API ──

@app.post("/api/review")
async def start_review(request: Dict[str, Any]) -> StreamingResponse:
    """启动赛后复盘并返回 SSE 事件流

    Args:
        request: JSON body，包含 match_id

    Returns:
        StreamingResponse: SSE 事件流
    """
    if review_api is None:
        raise HTTPException(status_code=503, detail="复盘 API 尚未初始化")
    match_id = request.get("match_id")
    if not match_id:
        raise HTTPException(status_code=422, detail="缺少 match_id")

    async def event_stream() -> AsyncGenerator[str, None]:
        async for sse_line in review_api.review_stream(str(match_id)):
            yield sse_line

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/review/{match_id}/status")
async def get_review_status(match_id: str) -> Dict[str, Any]:
    """获取复盘状态

    Args:
        match_id: 比赛 ID

    Returns:
        Dict[str, Any]: 复盘状态
    """
    if review_api is None:
        raise HTTPException(status_code=503, detail="复盘 API 尚未初始化")
    return await review_api.get_status(match_id)


@app.get("/api/review/{match_id}/report")
async def get_review_report(match_id: str) -> Dict[str, Any]:
    """获取复盘报告

    Args:
        match_id: 比赛 ID

    Returns:
        Dict[str, Any]: 复盘报告 JSON
    """
    if review_api is None:
        raise HTTPException(status_code=503, detail="复盘 API 尚未初始化")
    report = await review_api.get_report(match_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report.to_dict()


@app.post("/api/review/{match_id}/interrupt")
async def interrupt_review(match_id: str) -> Dict[str, Any]:
    """中断复盘

    Args:
        match_id: 比赛 ID

    Returns:
        Dict[str, Any]: 中断结果
    """
    if review_api is None:
        raise HTTPException(status_code=503, detail="复盘 API 尚未初始化")
    return await review_api.interrupt(match_id)


@app.get("/api/review/history")
async def list_review_history() -> List[Dict[str, Any]]:
    """获取复盘历史列表

    Returns:
        List[Dict[str, Any]]: 复盘历史
    """
    if review_api is None:
        raise HTTPException(status_code=503, detail="复盘 API 尚未初始化")
    return await review_api.list_history()


# ── Chat API（阶段 10 前由 MockReActAgent 填充） ──

@app.post("/api/chat")
async def chat(request: Dict[str, Any]) -> StreamingResponse:
    """聊天流式响应

    Args:
        request: JSON body，包含 message 与可选 session_id

    Returns:
        StreamingResponse: SSE/NDJSON 事件流
    """
    message = request.get("message", "")
    session_id = request.get("session_id")
    if not message:
        raise HTTPException(status_code=422, detail="缺少 message")

    async def event_stream() -> AsyncGenerator[str, None]:
        async for event in chat_agent.run_stream(str(message), session_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/history")
async def list_chat_history() -> List[Dict[str, Any]]:
    """获取聊天会话历史列表

    Returns:
        List[Dict[str, Any]]: 会话历史
    """
    return [
        {
            "session_id": item["session_id"],
            "title": item["title"],
            "updated_at": item["updated_at"],
        }
        for item in reversed(_chat_history)
    ]


@app.get("/api/sessions/{session_id}")
async def get_chat_session(session_id: str) -> Dict[str, Any]:
    """获取指定聊天会话详情

    Args:
        session_id: 会话 ID

    Returns:
        Dict[str, Any]: 会话详情
    """
    session = _chat_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session["session_id"],
        "title": session["title"],
        "created_at": session["created_at"],
        "updated_at": session["updated_at"],
        "messages": session["messages"],
    }


# ── 前端路由 ──

@app.get("/")
async def serve_index() -> FileResponse:
    """返回前端首页

    Returns:
        FileResponse: index.html
    """
    if INDEX_HTML.exists():
        return FileResponse(str(INDEX_HTML))
    raise HTTPException(
        status_code=503,
        detail="前端页面不存在，请检查 frontend/index.html",
    )


@app.get("/chat")
async def redirect_chat() -> "RedirectResponse":
    """旧 /chat 路径重定向到统一首页

    Returns:
        RedirectResponse: 重定向到 /
    """
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/")


@app.get("/{path:path}")
async def serve_spa(request: Request, path: str) -> FileResponse:
    """SPA 路由回退：静态文件优先，否则返回 index.html

    Args:
        request: FastAPI 请求对象
        path: 前端路由路径或静态资源路径

    Returns:
        FileResponse: 静态文件或 index.html
    """
    # 跳过 API 与 ward_analysis 路径（理论上不会被匹配到，保留作为防御）
    if path.startswith("api/") or path.startswith("ward_analysis/"):
        raise HTTPException(status_code=404, detail="Not found")
    if not INDEX_HTML.exists():
        raise HTTPException(
            status_code=503,
            detail="前端页面不存在，请检查 frontend/index.html",
        )
    # 尝试服务具体静态文件
    file_path = FRONTEND_DIR / path
    if path and file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    return FileResponse(str(INDEX_HTML))
