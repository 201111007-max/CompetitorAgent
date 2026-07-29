"""Dota Helper Web 入口

同时暴露赛后复盘端点（PostMatchReviewAPI）与 ReAct Agent Chat 端点。
Chat 后端由 DotaHelperReActAgent 驱动，通过 MCP 工具分发器调用 53 个分析工具。
"""
import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from dota_helper import PostMatchReviewAPI, create_default_api
from dota_helper.agent.react_agent import DotaHelperReActAgent
from dota_helper.agent.session_manager import SessionManager
from dota_helper.domain_types.events import ProgressEvent
from dota_helper.observability.logger import get_logger

logger = get_logger("web_app")

# 项目根目录与静态资源路径
PACKAGE_ROOT = Path(__file__).parent
WARD_DIR = PACKAGE_ROOT / "ward_analysis"
FRONTEND_DIR = PACKAGE_ROOT / "frontend"
INDEX_HTML = FRONTEND_DIR / "index.html"


# 全局状态
review_api: Optional[PostMatchReviewAPI] = None
chat_agent: Optional[DotaHelperReActAgent] = None
session_manager: Optional[SessionManager] = None


def _ensure_directories() -> None:
    """确保运行时目录存在"""
    WARD_DIR.mkdir(parents=True, exist_ok=True)
    FRONTEND_DIR.mkdir(parents=True, exist_ok=True)


def _create_ward_demo() -> None:
    """创建示例 ward HTML，供 Agent 引用"""
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

    初始化 PostMatchReviewAPI、DotaHelperReActAgent 和 SessionManager。
    Agent 通过 MCP Client 连接 MCP Server 获取 53 个工具描述。

    Args:
        app: FastAPI 应用实例
    """
    global review_api, chat_agent, session_manager
    _ensure_directories()
    _create_ward_demo()

    # 初始化复盘 API
    if review_api is None:
        logger.info("正在初始化 PostMatchReviewAPI...")
        review_api = create_default_api()
        logger.info("PostMatchReviewAPI 初始化完成")
    else:
        logger.info("PostMatchReviewAPI 已由外部注入，跳过默认初始化")

    # 初始化 ReAct Agent 和会话管理器
    if chat_agent is None:
        try:
            logger.info("正在初始化 DotaHelperReActAgent...")
            chat_agent = await DotaHelperReActAgent.create(enable_mcp=True)
            await chat_agent.__aenter__()
            session_manager = chat_agent._session_manager
            logger.info("DotaHelperReActAgent 初始化完成，MCP 已连接")
        except Exception as e:
            logger.warning(
                "DotaHelperReActAgent 初始化失败，聊天功能不可用: %s",
                str(e),
            )
            # 降级：创建独立的 SessionManager，聊天端点将返回错误提示
            session_manager = SessionManager()
    else:
        logger.info("DotaHelperReActAgent 已由外部注入，跳过默认初始化")
        session_manager = chat_agent._session_manager

    yield

    # 清理：关闭 MCP 连接
    if chat_agent is not None:
        try:
            await chat_agent.__aexit__(None, None, None)
        except Exception as e:
            logger.debug("Agent 清理异常（可忽略）: %s", str(e))

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


@app.get("/api/review/skills")
async def list_analysis_skills() -> List[Dict[str, Any]]:
    """列出所有可用的分析技能（内置 + 用户自定义）

    Returns:
        List[Dict[str, Any]]: 分析技能定义列表
    """
    if review_api is None:
        raise HTTPException(status_code=503, detail="复盘 API 尚未初始化")
    return review_api.list_analysis_skills()


@app.post("/api/review/skills")
async def register_analysis_skill(request: Dict[str, Any]) -> Dict[str, Any]:
    """注册用户自定义分析技能

    Args:
        request: JSON body，包含 name 和 skill_definition

    Returns:
        Dict[str, Any]: 注册结果
    """
    if review_api is None:
        raise HTTPException(status_code=503, detail="复盘 API 尚未初始化")
    name = request.get("name")
    skill_definition = request.get("skill_definition")
    if not name:
        raise HTTPException(status_code=422, detail="缺少 name")
    if not skill_definition:
        raise HTTPException(status_code=422, detail="缺少 skill_definition")
    try:
        review_api.register_analysis_skill(name, skill_definition)
        return {"status": "ok", "name": name}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ── Chat API（DotaHelperReActAgent 驱动） ──

@app.post("/api/chat")
async def chat(request: Dict[str, Any]) -> StreamingResponse:
    """聊天流式响应

    由 DotaHelperReActAgent 驱动，通过 MCP 工具分发器调用 53 个分析工具。
    Agent 不可用时返回错误提示。

    Args:
        request: JSON body，包含 message 与可选 session_id

    Returns:
        StreamingResponse: SSE/NDJSON 事件流
    """
    message = request.get("message", "")
    session_id = request.get("session_id")
    if not message:
        raise HTTPException(status_code=422, detail="缺少 message")

    if chat_agent is None:
        # Agent 不可用时返回降级提示
        async def fallback_stream() -> AsyncGenerator[str, None]:
            import uuid
            sid = session_id or f"sess_{uuid.uuid4().hex[:12]}"
            error_event = {
                "type": "error",
                "session_id": sid,
                "content": "Agent 暂时不可用，请稍后重试。",
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
        return StreamingResponse(
            fallback_stream(),
            media_type="text/event-stream",
        )

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
    if session_manager is None:
        return []
    summaries = await session_manager.list_sessions()
    return [s.to_dict() for s in summaries]


@app.get("/api/sessions/{session_id}")
async def get_chat_session(session_id: str) -> Dict[str, Any]:
    """获取指定聊天会话详情

    Args:
        session_id: 会话 ID

    Returns:
        Dict[str, Any]: 会话详情
    """
    if session_manager is None:
        raise HTTPException(status_code=503, detail="会话管理器未初始化")
    session = await session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.to_dict()


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
