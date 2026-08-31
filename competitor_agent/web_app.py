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
from importlib import resources
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from competitor_agent import CompetitorAnalysisAPI
from competitor_agent.config.loader import AppConfig, load_config
from competitor_agent.core.checkpoint import set_cancel
from competitor_agent.core.report_archiver import (
    _safe_filename,
    download_file_path,
    report_file_path,
    resolve_download_dir,
    resolve_output_dir,
    save_report_download,
    save_report_markdown,
)
from competitor_agent.core.report_settings import get_setting
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.domain_types.report import (
    CancelledResult,
    ChatResult,
    ComparisonReport,
    CompetitorReport,
)
from competitor_agent.interfaces.context import AnalysisSession
from competitor_agent.llm.client import LLMClient, StreamDelta
from competitor_agent.memory.four_layer_memory import FourLayerMemory
from competitor_agent.memory.session_history import SessionHistory
from competitor_agent.memory.timeline_memory import TimelineMemory
from competitor_agent.observability.logger import (
    read_session_log,
    setup_logging,
)
from competitor_agent.secret_vault import get_data_dir

logger = logging.getLogger("competitor_agent.web_app")

# ── 全局状态 ──────────────────────────────────────────────────────────────
_sessions: dict[str, dict[str, Any]] = {}  # session_id → {task, cancel_flag, ...}
_memory: FourLayerMemory | None = None
_config: AppConfig = load_config()
_history: SessionHistory | None = None

# 设计文档 50 P0/P1：事件队列挂起等待的超时（秒）——取消检查挂在该超时分支上，
# 取消响应延迟 ≤ 2×此值（原 50ms 忙轮询的折衷，避免队列空转 CPU）。
_EVENT_WAIT_TIMEOUT = 0.2
# 设计文档 63 §4.3：空闲期 SSE 心跳节流间隔（秒）——队列空挂起超时到点却无事件时，
# 每满一个间隔发一条 `: keep-alive\\n\\n` 注释保活，防 EventSource 超时断连。
_HEARTBEAT_INTERVAL = 10.0

# 设计文档 63 §3：叙述型事件 —— 其 message 属于 Lead 的实时叙述，曾收敛为 ``text_delta``。
# 设计文档 66 §3.5：叙述流与引擎内部标记分层——引擎内部无价值 phase（"开始 ReAct 推理"等
# 固定自证文案 / 子 Agent phase / 无 payload 语义的 progress）直接丢弃；Lead 有价值推进动作
# （"Lead 编排: {task}"）转独立 ``task`` 事件（前端 todo 清单行）。真实 LLM 叙述
# （thinking_delta/text_delta，带 turn）由 ``_stream_sink`` 原样投递，不受此收敛影响。
_NARRATIVE_EVENTS = frozenset({"phase_start", "phase_complete", "progress"})

# 引擎内部固定自证 phase 文案（对用户无信息价值，丢弃）
_ENGINE_BOILERPLATE = frozenset(
    {"开始 ReAct 推理", "ReAct 推理完成", "LangGraph 引擎启动", "LangGraph 引擎完成"}
)

# Lead 编排/对话推进动作前缀（→ task 事件）
_LEAD_ACTION_PREFIXES = ("Lead 编排:", "对话:")

# 设计文档 50 P2：前端静态资源（index.html/app.js/style.css/vendor）抽离自包内
# `static/`，经 package-data 纳入 wheel；`importlib.resources` 定位保证打包/源码一致。
_STATIC_DIR = resources.files("competitor_agent").joinpath("static")


def _get_memory() -> FourLayerMemory:
    global _memory
    if _memory is None:
        _memory = FourLayerMemory(data_dir=get_data_dir() / "memory")
    return _memory


_timeline: TimelineMemory | None = None


def _get_timeline() -> TimelineMemory:
    """竞品时间线记忆（设计文档 26 §3.4）：Web 端点 /api/timeline/{competitor} 读取。"""
    global _timeline
    if _timeline is None:
        _timeline = TimelineMemory(data_dir=get_data_dir())
    return _timeline


def _get_history() -> SessionHistory:
    """会话级多轮历史（设计文档 65 §3.2）：按 session_id 持久化对话上下文。"""
    global _history
    if _history is None:
        _history = SessionHistory(data_dir=get_data_dir())
    return _history


# ── SSE 辅助 ──────────────────────────────────────────────────────────────


def _lead_action_task(message: str) -> str | None:
    """Lead 编排/对话推进动作 → task 文案（前端 todo 清单行）；其他 → None。

    仅识别 ``phase_start "Lead 编排: {task}"`` / ``"对话: {task}"`` 这类 Lead 真实
    推进动作；引擎自证文案（"开始 ReAct 推理"等）与子 Agent phase 不在此列。
    """
    stripped = (message or "").strip()
    for prefix in _LEAD_ACTION_PREFIXES:
        if stripped.startswith(prefix):
            return stripped
    return None


def _narrative_sse(event: ProgressEvent, lead_id: str) -> str | None:
    """叙述型事件分层（设计文档 66 §3.5）→ SSE 串或 None（丢弃）。

    - 引擎内部无价值 phase（固定自证文案）→ 丢弃；
    - Lead 有价值推进动作（"Lead 编排: {task}" / "对话: {task}"）→ 独立 ``task``
      事件（payload: {message_id, task, status}）供前端渲染为清单行；
    - 其余引擎 phase/progress（无 payload 语义的纯推进）→ 丢弃，不再进正文 text_delta
      （挤行根因：多条引擎 phase 因 turn 全为 null 被前端合并到同一段）。
    """
    message = (event.message or "").strip()
    if not message or message in _ENGINE_BOILERPLATE:
        return None
    task_text = _lead_action_task(message)
    if task_text is not None:
        return ProgressEvent(
            event="task",
            phase="lead",
            message=task_text,
            payload={"message_id": lead_id, "task": task_text, "status": "running"},
        ).to_sse()
    return None


def _queue_sse(event: ProgressEvent, lead_id: str) -> str | None:
    """入队事件 → SSE 串或 None（丢弃）。

    设计文档 70 §8.3 D3a：api 层收尾发的**无 payload report 事件**（CLI/MCP 的「报告完成」
    信号）在 web 侧丢弃——否则前端 handleEvent 'report' 当真实报告渲染成空 dossier
    （title="report"、无正文、fetchStatus 缺 JSON → 默认「已批准」幽灵报告）。带 payload 的
    真实报告事件正常放行（单/对比收尾的 report 事件走旁路直接 yield，不经本队列）。
    其次沿用设计文档 66 §3.5 分层：叙述型事件转 task / 丢弃；其余原样透传。
    """
    if event.event == "report" and not event.payload:
        return None
    if event.event in _NARRATIVE_EVENTS:
        return _narrative_sse(event, lead_id)
    return event.to_sse()


async def _event_generator(
    session_id: str,
    task: str,
) -> AsyncIterator[str]:
    """SSE 事件生成器：逐条 yield ProgressEvent"""
    events_queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()
    # 设计文档 50 P0：在主线程（loop 运行中）捕获 loop 供工作线程 sink 跨线程投递。
    # 修复前在此调 asyncio.get_event_loop()——Python 3.11 起非主线程无 current loop 抛
    # RuntimeError 被 except 吞掉，Lead 分析期间所有中途进度事件被静默丢弃（已实证）。
    loop = asyncio.get_running_loop()

    def _on_event(event: ProgressEvent) -> None:
        """将事件推入 asyncio 队列（线程安全，供 run_in_executor 工作线程回调）"""
        try:
            loop.call_soon_threadsafe(events_queue.put_nowait, event)
        except RuntimeError:
            # generator 已关闭后的迟到事件（会话结束边界）：记录 debug 而非静默丢弃
            logger.debug("会话 %s 已关闭，迟到事件丢弃: %s", session_id, event.event)

    llm_client = LLMClient(
        model=_config.llm.model,
        base_url=_config.llm.api_base_url,
        fallback_models=_config.llm.fallback_models,
        timeout=_config.llm.timeout,
        max_retries=_config.llm.max_retries,
        pricing_per_1k=_config.llm.pricing_per_1k,
    )
    # 设计文档 63 §5.5：单条 Lead 助手消息的归属 message_id——后续 text_delta / text.stop /
    # message.stop 全部复用；前端按它把增量归位到 Lead 气泡。
    lead_id = f"lead_{uuid.uuid4().hex[:6]}"

    def _stream_sink(delta: StreamDelta) -> None:
        """仅 Lead 流式旁路（默认关闭，仅本 Web 触发）：流式增量 → 对话事件投递。

        ``thinking`` → ``thinking_delta``（前端折叠"已思考"）；``text`` → ``text_delta``
        （打字机），统一归位到 lead_id 气泡，跨线程经 ``_on_event`` 安全入队。
        设计文档 64 §3.4：payload 透传 ``turn``（assistant 步序）供前端分段渲染。
        """
        kind = "thinking_delta" if delta.kind == "thinking" else "text_delta"
        try:
            _on_event(
                ProgressEvent(
                    event=kind,
                    phase="lead",
                    message=delta.text,
                    payload={"message_id": lead_id, "delta": delta.text, "turn": delta.turn},
                )
            )
        except Exception:
            logger.warning("Lead 流式增量投递失败", exc_info=True)

    api_with_sink = CompetitorAnalysisAPI(
        llm=llm_client,
        use_llm=True,
        memory=_get_memory(),
        event_sink=_on_event,
        stream_sink=_stream_sink,
        config=load_config(),
    )

    # 设计文档 65 §3.3：多轮会话历史——读该 session_id 历史 + 追加本轮 user task；
    # 历史写入失败仅告警不阻塞分析（边界与回退，§3.5）。
    history_store = _get_history()
    history_messages = history_store.messages(session_id) if session_id else []
    try:
        history_store.append(session_id, "user", task)
    except Exception:
        logger.warning("会话历史 user 落盘失败（不影响分析）", exc_info=True)

    # 统一入口 run()（设计文档 62 §3.7）：解析/分派收敛到库内，HTTP 层不再写 DISCOVERY/COMPARE
    # 分支；LLM 不可用 → 抛可读错误由外层转 SSE error。
    # 设计文档 64 §5：run() 意图门控可返回 ChatResult（普通提问 → 无报告面板）。
    async def _run_analysis() -> CompetitorReport | ComparisonReport | ChatResult:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None,
                lambda: api_with_sink.run(
                    task, session_id=session_id, history_messages=history_messages
                ),
            )
        except Exception as exc:  # LLM 不可用 → 可读错误，Web 普查不崩溃
            raise RuntimeError(f"需要配置 LLM API Key 才能分析（LLM 不可用: {exc}）") from exc

    analysis_task = asyncio.create_task(_run_analysis())

    def _text_stop(final: bool) -> str:
        return ProgressEvent(
            event="text.stop",
            phase="lead",
            payload={"message_id": lead_id, "final": final},
        ).to_sse()

    try:
        # 先发送 session_started + Lead 消息开始
        yield ProgressEvent(
            event="session_started",
            phase="init",
            message=f"会话 {session_id} 已启动",
            payload={"session_id": session_id},
        ).to_sse()
        yield ProgressEvent(
            event="message.start",
            phase="lead",
            message="开始分析",
            payload={"message_id": lead_id, "source": "lead", "task": task},
        ).to_sse()

        # 挂起等待事件而非 50ms 忙轮询（设计文档 50 §2.2）：队列空时 await 挂起，
        # 取消检查挂在 wait_for 超时分支，保持取消响应 ≤200ms（原 50ms 的折衷）。
        last_heartbeat = time.monotonic()  # 设计文档 63 §4.3：空闲心跳节流时间戳
        while not analysis_task.done():
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

            try:
                event = await asyncio.wait_for(
                    events_queue.get(), timeout=_EVENT_WAIT_TIMEOUT
                )
            except asyncio.TimeoutError:
                # 空闲挂起超时（队列空）：按节流间隔发心跳保活（SSE 注释，不触发事件）
                if time.monotonic() - last_heartbeat >= _HEARTBEAT_INTERVAL:
                    yield ": keep-alive\n\n"
                    last_heartbeat = time.monotonic()
                continue
            # 事件转发（设计文档 66 §3.5 分层 + 设计文档 70 §8.3 D3 无 payload report 丢弃）；
            # 返回 None 的事件丢弃，其余原样透传
            sse = _queue_sse(event, lead_id)
            if sse is not None:
                yield sse

        # 分析完成：排空残余事件，防"完成瞬间队列中事件丢失"（设计文档 50 §3.3 ②）
        while not events_queue.empty():
            event = events_queue.get_nowait()
            sse = _queue_sse(event, lead_id)
            if sse is not None:
                yield sse

        # 分析完成，获取报告
        report = analysis_task.result()
        # 设计文档 65 §3.2：收尾把本轮结果追加进会话历史（chat→answer 原文；分析→紧凑摘要，
        # 不存整份 markdown/JSON，避免历史膨胀与污染）。失败仅告警不阻塞。
        try:
            if isinstance(report, ChatResult):
                history_store.append(session_id, "assistant", report.answer or "对话完成")
            elif isinstance(report, ComparisonReport):
                names = " / ".join(c.name for c in report.competitors) or "compare"
                history_store.append(
                    session_id,
                    "assistant",
                    f"对比报告完成：{names}（{len(report.reports)} 个竞品）",
                )
            elif isinstance(report, CompetitorReport):
                history_store.append(
                    session_id,
                    "assistant",
                    f"分析完成：{report.competitor.name}（{len(report.dimension_results)} 个维度）",
                )
        except Exception:
            logger.warning("会话历史 assistant 落盘失败（不影响分析）", exc_info=True)
        # 收敛 Lead 消息的正文流：text.stop(final) → 前端收光标、停打字机（设计文档 63 §7.3）。
        # 延迟到终态确定后发，保证它排在所有 text_delta 之后。
        yield _text_stop(True)
        # 设计文档 64 §5：对话式分支——答案已经 Stream 通道（text_delta/thinking_delta）呈现，
        # 无 report 面板/无维度/无置信度，仅收敛 message.stop。
        if isinstance(report, ChatResult):
            yield ProgressEvent(
                event="message.stop",
                phase="lead",
                message="对话完成",
                payload={
                    "message_id": lead_id,
                    "source": "lead",
                    "summary": report.answer or "对话完成",
                },
            ).to_sse()
            return
        if isinstance(report, CancelledResult):
            yield ProgressEvent(
                event="message.stop",
                phase="report",
                message="分析已取消，返回部分结果",
                payload={
                    "message_id": lead_id,
                    "source": "lead",
                    "summary": f"分析已取消，返回 {len(report.dimension_results)} 个已完成维度",
                },
            ).to_sse()
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
            name = " / ".join(c.name for c in report.competitors) or "compare"
            # 自动落盘对比报告（先落盘，地址随事件下发；幂等 safe 名与 report_file_path 命名一致）
            saved_path = save_report_markdown(report)
            try:
                # 设计文档 70：分析完成写下载副本（<download>/<name>.md，失败不影响主流程）
                save_report_download(report)
            except Exception:
                logger.warning("对比报告下载副本落盘失败（不影响主流程）", exc_info=True)
            yield ProgressEvent(
                event="report",
                phase="report",
                progress=1.0,
                message=f"对比报告生成完成，{len(report.reports)} 个竞品 / {len(set(all_dims))} 个维度",
                payload={
                    "competitor": name,
                    "terminal_state": "compare",
                    "overall_confidence": max(
                        (r.overall_confidence for r in report.reports), default=0.0
                    ),
                    "dimensions": list(dict.fromkeys(all_dims)),
                    "markdown_report": report.markdown_report,
                    "session_id": session_id,
                    "is_comparison": True,
                    # 设计文档 70 §8.1 D1b：候选为 0 → false（前端据此提示"未收集到候选数据"）
                    "has_candidates": bool(report.reports),
                    "report_url": f"/api/reports/{_safe_filename(name)}/download",
                    "report_path": str(saved_path),
                },
            ).to_sse()
            # 收敛 Lead 消息为 `message.stop`（summary 供多轮回灌/前端状态）
            yield ProgressEvent(
                event="message.stop",
                phase="report",
                message="分析完成",
                payload={
                    "message_id": lead_id,
                    "source": "lead",
                    "summary": f"对比报告完成，{len(report.reports)} 个竞品",
                },
            ).to_sse()
            # 归档会话（设计文档 70 §8.1 D1a：空名 "compare" 兜底 + 整体 try/except——
            # 零候选/归档失败仅告警，永不阻塞 SSE 主流程）
            try:
                names = " / ".join(c.name for c in report.competitors) or "compare"
                _get_memory().archive_session(
                    AnalysisSession(
                        task=task,
                        competitor_name=names,
                        session_id=session_id,
                        raw={
                            "markdown_report": report.markdown_report,
                            "terminal_state": "compare",
                            "dimension_count": len(set(all_dims)),
                            "competitor_name": names,
                            "created_at": report.created_at,
                        },
                    )
                )
            except Exception:
                logger.warning("对比会话归档失败（不影响主流程）", exc_info=True)
            return

        # 自动落盘 <output>/<竞品>.md（导出/下载用），先落盘再下发地址
        saved_path = save_report_markdown(report)
        try:
            # 设计文档 70：分析完成写下载副本（<download>/<竞品>.md，失败不影响主流程）
            save_report_download(report)
        except Exception:
            logger.warning("报告下载副本落盘失败（不影响主流程）", exc_info=True)
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
                "report_url": f"/api/reports/{_safe_filename(report.competitor.name)}/download",
                "report_path": str(saved_path),
            },
        ).to_sse()
        # 收敛 Lead 消息为 `message.stop`（summary 供多轮回灌/前端状态）
        yield ProgressEvent(
            event="message.stop",
            phase="report",
            message="分析完成",
            payload={
                "message_id": lead_id,
                "source": "lead",
                "summary": f"{report.competitor.name} 报告完成，{len(report.dimension_results)} 个维度",
            },
        ).to_sse()

        # 归档会话（统一 raw schema + freshness 元数据）；设计文档 70 §8.1 D1a：
        # 归档失败仅告警，永不阻塞 SSE 主流程
        try:
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
                    "freshness": report.freshness.to_dict() if report.freshness else None,
                    # 设计文档 35：结构化维度 + 遗留缺口，供会话摘要/相关度召回
                    "dimensions": [
                        {"dimension": r.dimension, "summary": r.summary, "confidence": r.confidence}
                        for r in report.dimension_results
                    ],
                    "pending_gaps": [g.field for g in report.gaps_pending],
                },
            )
        )
        except Exception:
            logger.warning("会话归档失败（不影响主流程）", exc_info=True)

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
    # 设计文档 67 §2.3.1：schedule.enabled 时启动内置调度器（可选补充，与外部 cron 二选一）
    _scheduler = None
    if getattr(_config.schedule, "enabled", False):
        try:
            from competitor_agent.core.scheduler import WeeklyScheduler

            api = _build_api_for_scheduler()
            _scheduler = WeeklyScheduler(
                lambda: api.run_scheduled(),
                interval_hours=_config.schedule.interval_hours,
                cron_expr=getattr(_config.schedule, "cron_expr", ""),
            )
            _scheduler.start()
        except Exception:
            logger.warning("内置调度器启动失败（不影响 Web）", exc_info=True)
    yield
    if _scheduler is not None:
        _scheduler.stop()
    logger.info("竞品分析 Web 服务关闭")


def _build_api_for_scheduler() -> CompetitorAnalysisAPI:
    """构造调度轮专用 API（复用 web 的 llm/记忆装配，事件走模块级记录）。"""
    llm_client = LLMClient(
        model=_config.llm.model,
        base_url=_config.llm.api_base_url,
        fallback_models=_config.llm.fallback_models,
        timeout=_config.llm.timeout,
        max_retries=_config.llm.max_retries,
        pricing_per_1k=_config.llm.pricing_per_1k,
    )
    return CompetitorAnalysisAPI(
        llm=llm_client,
        use_llm=True,
        memory=_get_memory(),
        config=load_config(),
    )


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
    """前端页面：从包内 static/index.html 读取（设计文档 50 §2.4/§3.2）。"""
    return _STATIC_DIR.joinpath("index.html").read_text(encoding="utf-8")


# 静态资源（css/js/vendor）：设计文档 50 P2 抽离内嵌 HTML，避免改动前端需动 .py
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


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


@app.get("/api/timeline/{competitor}")
async def timeline(
    competitor: str,
    _: None = Depends(require_auth),
    limit: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    """查询竞品时间线事件（版本/功能/价格/榜单变化，设计文档 26 §3.4）。"""
    events = _get_timeline().events(competitor, limit=limit)
    return JSONResponse(
        {
            "competitor": competitor,
            "count": len(events),
            "events": [e.__dict__ for e in events],
        }
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
    """返回落盘的报告文件 <data_dir>/reports/competitor/<competitor>.md；不存在返回 404。"""
    path = report_file_path(competitor)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"报告不存在: {competitor}")
    return FileResponse(path, media_type="text/markdown; charset=utf-8")


@app.get("/api/reports/{competitor}/download")
async def report_download(
    competitor: str,
    _: None = Depends(require_auth),
) -> FileResponse:
    """以 Content-Disposition: attachment 下载报告（触发浏览器下载）。

    设计文档 70：下载目录（download/）优先 → 归档目录（output/，含旧归档回退）。
    """
    path = download_file_path(competitor)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"报告不存在: {competitor}")
    return FileResponse(path, media_type="text/markdown; charset=utf-8", filename=f"{competitor}.md")


@app.get("/api/settings")
async def settings_get(
    _: None = Depends(require_auth),
) -> JSONResponse:
    """读取报告目录设置（设计文档 70）：当前生效值 + data_dir + 默认值。

    ``report_output_dir``/``report_download_dir`` 为当前生效路径（settings 覆盖后）；
    ``data_dir`` 为 settings.json 所在目录；``defaults`` 为代码默认（项目 output/download）。
    """
    return JSONResponse(_settings_payload())


@app.put("/api/settings")
async def settings_put(
    request: Request,
    _: None = Depends(require_auth),
) -> JSONResponse:
    """写入报告目录设置（设计文档 70）：PUT {"report_output_dir": "...", "report_download_dir": "..."}。

    传 ``""`` 即重置为默认；**值等于项目默认目录时也存空串**（保持"空 = 派生默认"，
    避免把绝对路径固化进 settings.json，项目迁移后失效）；原子写 settings.json；返回更新后结果。
    """
    from competitor_agent.core.report_settings import (
        default_download_dir,
        default_output_dir,
        write_settings,
    )

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="请求体需为 JSON 对象")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="请求体需为 JSON 对象")
    updates = {
        "report_output_dir": _normalize_dir_setting(body.get("report_output_dir", ""), default_output_dir()),
        "report_download_dir": _normalize_dir_setting(body.get("report_download_dir", ""), default_download_dir()),
    }
    try:
        write_settings(updates)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"设置写入失败: {exc}")
    return JSONResponse(_settings_payload())


def _is_abs_like(v: str) -> bool:
    """绝对路径判定兼容 Windows 盘符：``Path("D:\\...").is_absolute()`` 在 Linux 上为 False
    （CI/Linux 会把 ``D:/x`` 当相对路径拼到 CWD 破坏比较），此处显式识别盘符前缀。"""
    return len(v) >= 3 and v[0].isalpha() and v[1] == ":" and v[2] in ("/", "\\")


def _normalize_dir_setting(value: str, default: Path) -> str:
    """设置值规范化：等于项目默认目录（含斜杠/大小写差异）→ 存空串（保持派生，不固化绝对路径）；否则原样存。

    ``~`` 展开、相对路径按 CWD 解析后与默认做大小写/分隔符无关比较；空串即默认原样返回。
    """
    v = str(value or "").strip()
    if not v:
        return ""
    p = Path(v).expanduser()
    if not p.is_absolute() and not _is_abs_like(str(p)):
        p = Path.cwd() / p
    norm = lambda path: str(path).replace("\\", "/").lower()
    if norm(p) == norm(default):
        return ""
    return v


def _settings_payload() -> dict[str, object]:
    """设置响应载荷（GET/PUT 共用）。"""
    from competitor_agent.core.report_settings import (
        default_download_dir,
        default_output_dir,
        settings_path,
    )

    return {
        "report_output_dir": get_setting("report_output_dir") or str(resolve_output_dir()),
        "report_download_dir": get_setting("report_download_dir") or str(resolve_download_dir()),
        "data_dir": str(settings_path().parent),
        "defaults": {
            "report_output_dir": str(default_output_dir()),
            "report_download_dir": str(default_download_dir()),
        },
    }


@app.get("/api/reports/{competitor}/status")
async def report_status_endpoint(
    competitor: str,
    _: None = Depends(require_auth),
) -> JSONResponse:
    """查询报告审批状态（设计文档 67 §3.2：pending_review 前端标"待人工确认"徽章）。"""
    from competitor_agent.core.approval_gate import report_json_path, report_status

    path = report_json_path(competitor)
    status = report_status(path) if path.exists() else "approved"
    return JSONResponse(
        {
            "competitor": competitor,
            "status": status,
            "path": str(path),
        }
    )


@app.post("/api/reports/{competitor}/review")
async def report_review(
    competitor: str,
    request: Request,
    _: None = Depends(require_auth),
) -> JSONResponse:
    """人工审批：POST {"action": "approve"|"reject", "note": "..."}（设计文档 67 §3.2）。

    approve → status=approved；reject → status=rejected + reviewer_note 回灌注释。
    """
    from competitor_agent.core.approval_gate import report_json_path, set_report_status

    path = report_json_path(competitor)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"报告 JSON 不存在: {competitor}")
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="请求体需为 JSON: {\"action\": \"approve|reject\", \"note\": \"...\"}")
    action = str(body.get("action") or "").lower()
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action 需为 approve | reject")
    note = str(body.get("note") or "")
    try:
        data = set_report_status(path, "approved" if action == "approve" else "rejected", reviewer_note=note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse(
        {
            "competitor": competitor,
            "status": data.get("status"),
            "reviewed_at": data.get("reviewed_at"),
            "reviewer_note": data.get("reviewer_note"),
        }
    )


def main() -> None:
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="竞品分析 Agent Web 服务")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="监听地址")
    args = parser.parse_args()

    # 设计文档 74 §3.1/E2：启动强制应用用户级 env（忽略 shell 注入的 DEEPSEEK_API_KEY / OPENAI_BASE_URL）
    from competitor_agent.config.user_env import apply_user_level_environment

    apply_user_level_environment()

    setup_logging(level=_config.observability.log_level, log_dir=get_data_dir() / "logs")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
