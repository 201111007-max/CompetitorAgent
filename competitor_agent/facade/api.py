"""CompetitorAnalysisAPI — 外部唯一入口

主路径（设计文档 47/49）：Lead ReAct 编排的多 Agent 流程——
``analyze()`` 即 Lead Agent 推理循环：首步强制 ``make_plan``，之后由 LLM 自主
委派维度子 Agent（``delegate`` 后台并发 + 结果回填）、调用复核工具
（validate_facts/detect_conflict/check_freshness/select_source）、补证收尾，
最后以 REPORT_SCHEMA JSON 收尾 → ``react_report.assemble`` → CompetitorReport。
无 Key / LLM 不可用 → LLMUnavailableError（无静默规则降级，47 语义）。

M4 新增：analyze_stream()（流式 SSE）/ cancel() / resume() / get_history()。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, cast

from competitor_agent.agent.aggregate_tool import make_aggregate_tool
from competitor_agent.agent.delegate_tool import (
    DelegateRunner,
    SubagentRuntime,
    make_delegate_tool,
)
from competitor_agent.agent.make_plan import build_make_plan_tool
from competitor_agent.agent.prompts.react_system import build_lead_system_prompt
from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.agent.react_loop import ReactLoop, ReactRunResult
from competitor_agent.agent.review_tools import (
    build_check_freshness_tool,
    build_detect_conflict_tool,
    build_select_source_tool,
    build_validate_facts_tool,
    extract_verified_facts,
)
from competitor_agent.agent.subagent_registry import (
    build_subagent,
    get_subagent_registry,
)
from competitor_agent.agent.tool_dispatcher import ToolSpec
from competitor_agent.agent.tool_registry import build_react_dispatcher
from competitor_agent.collector.web_extractor import WebExtractor
from competitor_agent.config.loader import AppConfig, load_config
from competitor_agent.core.alerting import Alert, AlertSink, ConsoleAlertSink
from competitor_agent.core.alerting import report_diff as _diff_to_alerts
from competitor_agent.core.budget import IterationBudget
from competitor_agent.core.budget_controller import BudgetController
from competitor_agent.core.checkpoint import (
    checkpoint_to_report,
    clear_cancel,
    delete_checkpoint,
    is_cancelled,
    load_checkpoint,
    save_checkpoint,
    set_cancel,
)
from competitor_agent.core.competitor_discoverer import CompetitorDiscoverer
from competitor_agent.core.input_sanitizer import sanitize_task
from competitor_agent.core.report_builder import ReportBuilder
from competitor_agent.core.report_exporter import (
    export_comparison_json,
    export_competitor_json,
)
from competitor_agent.core.task_parser import ResolutionDecision, parse_task
from competitor_agent.core.url_guard import URLError, guard_http_url
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import GapStatus, ResultStatus
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.domain_types.freshness import ReportFreshness, stale_under_ttl
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import SourceEvidence
from competitor_agent.domain_types.pricing import profile_from_details
from competitor_agent.domain_types.report import (
    CancelledResult,
    ComparisonReport,
    CompetitorReport,
    DimensionResult,
)
from competitor_agent.facade import react_report
from competitor_agent.interfaces.context import (
    AnalysisSession,
    ChatMessage,
    Skill,
    SourceContext,
)
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.llm.client import LLMClient
from competitor_agent.memory.timeline_memory import TimelineMemory
from competitor_agent.observability.logger import (
    close_session_log,
    get_session_logger,
    log_event,
    set_current_session,
)

logger = logging.getLogger("competitor_agent.facade.api")

# Lead Agent 推理步数上限（设计文档 49：make_plan → delegate → 复核 → Final Answer）
_LEAD_MAX_STEPS = 12


def _delegate_section_url(result: str, dimension: str) -> str:
    """delegate 批量回填文本中该维度子结果块的首个 URL（按结果头切分）。"""
    import re as _re

    marker = f"[维度子 Agent 结果: {dimension}"
    idx = result.find(marker)
    if idx < 0:
        marker = f"（请分析维度：{dimension}）"
        idx = result.find(marker)
    if idx < 0:
        return ""
    match = _re.search(r"https?://[^\s\"'<>\]\)]+", result[idx:])
    return match.group(0) if match else ""


class CompetitorAnalysisAPI:
    """竞品分析外部入口"""

    def __init__(
        self,
        llm: LLMClient | None = None,
        use_llm: bool = True,
        max_iterations: int | None = None,
        cost_limit: float | None = None,
        event_sink: Callable[[ProgressEvent], None] | None = None,
        extractor: WebExtractor | None = None,
        memory: IFourLayerMemory | None = None,
        config: AppConfig | None = None,
        web_tool: Callable[[str], list[dict]] | None = None,
        timeline: TimelineMemory | None = None,
        enable_rag: bool = True,  # 设计文档 30：消融开关（默认开启，行为不变）
        enable_memory: bool = True,  # 设计文档 30：消融开关（默认开启，行为不变）
        rag_store: object | None = None,  # 设计文档 30：消融可注入共享知识库实例
        vector_store: object | None = None,  # 设计文档 32：可注入向量层（测试/评测确定性 mock）
        tool_dispatcher: object | None = None,  # 历史兼容：已由 Lead 工具面取代，保留签名
        engine: str = "react",  # 设计文档 51：编排引擎 "react"（默认）| "langgraph"
        tracer: Any = None,  # 设计文档 54：链路追踪底座（None 用模块单例，默认 JsonlSink）
        max_parallel_tool_calls: int = 4,  # 设计文档 59：单回合多 tool_calls 并发上限；1 = 串行
    ) -> None:
        # 配置注入：显式参数优先，其次 config，最后默认值
        cfg = config or load_config()
        if engine not in ("react", "langgraph"):
            raise ValueError(f"未知编排引擎: {engine!r}（可用: react | langgraph）")
        if engine == "langgraph":
            # 构造期检查（设计文档 51 §2.2）：未装 langgraph → 可读 ImportError
            from competitor_agent.agent.langgraph_engine import ensure_langgraph_available

            ensure_langgraph_available()
        self._engine = engine
        max_iterations = max_iterations if max_iterations is not None else cfg.budget.max_iterations
        cost_limit = cost_limit if cost_limit is not None else cfg.budget.cost_limit_usd
        self._config = cfg
        self._llm = llm
        self._use_llm = use_llm
        self._event_sink = event_sink
        # enable_memory=False：门控全部记忆副作用（set_success_rates / _apply_memory_boost /
        # record_skill / record_outcome / archive_session），下游均判 `self._memory is None`
        self._memory = memory if enable_memory else None
        self._tool_dispatcher = tool_dispatcher
        self._max_parallel_tool_calls = max_parallel_tool_calls

        self._extractor = extractor or WebExtractor()
        # 新鲜度 TTL（设计文档 26）：build() 为报告计算 freshness 元数据
        self._builder = ReportBuilder(dimension_ttl_days=cfg.freshness.dimension_ttl_days)
        self._budget = BudgetController(max_iterations=max_iterations, cost_limit=cost_limit)
        # 竞品时间线记忆（设计文档 26 §3.4）：跨分析 diff，独立于四层记忆
        self._timeline = timeline or TimelineMemory()

        # RAG 知识库：分析后摄入 + Lead/子 Agent 检索注入（外部事实依据，降低幻觉）
        # enable_rag=False：不组装知识库，Lead/子 Agent 对 None 走"跳过检索"路径
        if enable_rag:
            from competitor_agent.knowledge_base.competitor_store import CompetitorStore
            from competitor_agent.knowledge_base.ingester import Ingester
            from competitor_agent.knowledge_base.retriever import Retriever
            from competitor_agent.knowledge_base.vector_store import VectorStore

            # 向量层（设计文档 32）：注入的优先；默认 VectorStore 懒加载——嵌入模型
            # 不可用（未缓存/未装依赖）时 is_available()=False，检索自动降级纯词袋，行为不变
            if vector_store is not None:
                self._vector_store = vector_store
            else:
                self._vector_store = VectorStore()
            self._store = rag_store or CompetitorStore(vector_store=self._vector_store)
            self._ingester = Ingester(store=self._store)
            self._retriever = Retriever(store=self._store)

            # 记忆召回向量层（设计文档 52 §2.1）：独立 collection 与知识库隔离，
            # 注入 L1 会话归档；嵌入模型不可用/未装 rag extra 时 is_available()=False，
            # 记忆召回保持词袋路径，行为与现状逐位一致
            from competitor_agent.memory.four_layer_memory import FourLayerMemory

            if isinstance(self._memory, FourLayerMemory):
                self._memory.attach_vector_store(
                    VectorStore(collection_name="session_summaries", data_dir=self._memory.data_dir)
                )

            # 启动状态日志（设计文档 52 §2.2）：消除静默降级
            vs = cast(VectorStore, self._vector_store)
            if vs.is_available():
                logger.info("向量层状态: available(%s)", vs.model_name)
            else:
                logger.info("向量层状态: degraded(模型 %s 未缓存，降级词袋)", vs.model_name)
        else:
            self._store = None
            self._ingester = None
            self._retriever = None
            self._vector_store = None

        # 竞品发现器（设计文档 20）：仅 DISCOVERY 意图时被调用，web_tool 可注入
        self._discoverer = CompetitorDiscoverer(llm=llm, use_llm=use_llm, web_tool=web_tool)

        # 设计文档 54：链路追踪底座。显式注入优先（测试隔离）；否则模块单例。
        # 可选 Langfuse exporter：ObservabilityConfig.langfuse_enabled 派生属性为真时才
        # 追加（宿主/公钥/密钥三环境变量齐全 + SDK 可导入），否则纯本地 JsonlSink。
        from competitor_agent.observability.langfuse_exporter import LangfuseExporter
        from competitor_agent.observability.tracer import JsonlSink, Tracer, get_tracer

        if tracer is not None:
            self._tracer = tracer
        elif self._config.observability.langfuse_enabled:
            self._tracer = Tracer(sinks=[JsonlSink(), LangfuseExporter()])
        else:
            self._tracer = get_tracer()

    def analyze(
        self,
        task: str,
        conversation_history: list[ChatMessage] | None = None,
        mode: str = "team",
        session_id: str | None = None,
    ) -> CompetitorReport:
        """单竞品分析（设计文档 49）：Lead ReAct 编排 → CompetitorReport。

        Args:
            task: 用户任务文本（入站先做浅清洗 sanitize_task）
            conversation_history: 上一轮对话历史（ChatMessage 列表），
                传入则把前序上下文摘要并入任务解析，支持多轮追问。
            mode: 已废弃（历史兼容，仅告警）；统一走 Lead ReAct 编排。
            session_id: 外部会话 ID（如 Web 端 sid）。传入时复用，使内部取消标志
                与外部一致（解决 Web 取消断链）；留空则自动生成。
        """
        if mode != "team":
            logger.warning("mode 参数已废弃（历史兼容），统一走 Lead ReAct 编排，忽略 mode=%s", mode)
        task = sanitize_task(task)
        task = self._disambiguate_with_history(task, conversation_history)
        sid = session_id or f"sess_{uuid.uuid4().hex[:8]}"
        set_current_session(sid)
        # 设计文档 54：trace 生命周期——trace_id 即 session_id，覆盖本次分析
        # （含并行子 Agent 的跨线程 span，经 Tracer._traces 聚合 cost/token）。
        self._tracer.start_trace("analyze", trace_id=sid, input_brief=task)
        try:
            slog = get_session_logger(sid)
            log_event(slog, "session_started", "init", f"会话 {sid} 启动", task=task)
            self._emit(
                ProgressEvent(
                    event="phase_start",
                    phase="langgraph" if self._engine == "langgraph" else "react",
                    message=f"{'LangGraph' if self._engine == 'langgraph' else 'Lead'} 编排: {task}",
                )
            )

            if self._engine == "langgraph":
                # 设计文档 51：LangGraph 引擎——取消/预算/checkpoint 不对齐（差异化结论）
                plan, answer, transcript = self._run_langgraph_engine(task, sid)
                terminal = "success"
            else:
                loop, result = self._run_react_loop(task, sid)
                plan, answer, transcript = loop.plan, result.answer, result.transcript
                terminal = (
                    "cancelled"
                    if result.cancelled
                    else ("partial" if result.budget_exhausted else "success")
                )
            report = react_report.assemble(
                lead_answer=answer,
                competitor=self._lead_competitor(task, plan),
                loop_plan=plan,
                transcript=transcript,
                builder=self._builder,
                terminal_state=terminal,
            )
            log_event(
                slog, "report.built", "report",
                f"报告生成，{len(report.dimension_results)} 个维度",
                dimension_count=len(report.dimension_results),
                overall_confidence=round(report.overall_confidence, 3),
            )
            # 记忆沉淀（唯一写侧）：成功与取消部分结果都沉淀（对齐 single 路径）
            self._record_memory_success(report, transcript)
            if is_cancelled(sid):
                # 取消完成：保留 checkpoint 供 /resume 续跑，返回带部分结果的取消报告
                logger.info("会话 %s 取消后返回部分结果（%d 个维度）", sid, len(report.dimension_results))
                self._save_checkpoint_for_resume(sid, task, report)
                close_session_log(sid)
                self._emit(
                    ProgressEvent(
                        event="cancelled",
                        phase="report",
                        message=f"分析已取消，返回 {len(report.dimension_results)} 个已完成维度",
                    )
                )
                self._tracer.end_trace(
                    sid, status="cancelled", output_brief=report.markdown_report
                )
                return CancelledResult(
                    competitor=report.competitor,
                    dimension_results=report.dimension_results,
                    overall_score=report.overall_score,
                    overall_confidence=report.overall_confidence,
                    gaps_pending=report.gaps_pending,
                    markdown_report=report.markdown_report,
                    terminal_state="cancelled",
                    created_at=report.created_at,
                    cancelled=True,
                )
            # 分析正常完成：记录时间线 diff + 归档带新鲜度的会话（设计文档 26）
            self._record_timeline(report)
            self._archive_report(report, task, sid)
            self._export_competitor_json(report, sid)
            delete_checkpoint(sid)
            close_session_log(sid)
            self._emit(
                ProgressEvent(
                    event="report",
                    phase="report",
                    progress=1.0,
                    message=f"报告生成完成，终态={terminal}",
                )
            )
            self._tracer.end_trace(sid, status=terminal, output_brief=report.markdown_report)
            return report
        except Exception:
            # 异常路径：闭合 trace 为 error，避免残留悬半根节点（设计文档 54 §2.2）
            self._tracer.end_trace(sid, status="error", output_brief="")
            raise

    @property
    def memory(self) -> IFourLayerMemory | None:
        return self._memory

    @property
    def timeline(self) -> TimelineMemory:
        """竞品时间线记忆（设计文档 26）：跨分析 diff 的事件仓库。"""
        return self._timeline

    def _record_timeline(self, report: CompetitorReport) -> None:
        """记录竞品时间线 diff（设计文档 26 §3.4），并把事件段落追加进 Markdown。"""
        try:
            events = self._timeline.update(report)
        except Exception:  # 时间线记录失败不影响主流程，仅告警
            logger.warning("时间线记录失败: %s", report.competitor.name, exc_info=True)
            return
        if events:
            section = self._builder.render_timeline(events)
            if section:
                report.markdown_report = report.markdown_report.rstrip() + "\n\n" + section + "\n"

    def _archive_report(self, report: CompetitorReport, task: str, session_id: str) -> None:
        """归档会话（统一 raw schema + freshness 元数据 + 定价画像），
        供 refresh_stale 判定过期、定价成本对比与时间线 diff。"""
        if self._memory is None:
            return
        pricing_profiles = [
            profile.to_dict()
            for r in report.dimension_results
            if r.dimension == "pricing"
            and isinstance(r.details, dict)
            and (profile := profile_from_details(r.details, r.evidence or [])).has_pricing_data
        ]
        self._memory.archive_session(
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
                    "pricing_profiles": pricing_profiles,
                    # 设计文档 35：结构化维度 + 遗留缺口，供会话摘要/相关度召回
                    "dimensions": [
                        {"dimension": r.dimension, "summary": r.summary, "confidence": r.confidence}
                        for r in report.dimension_results
                    ],
                    "pending_gaps": [g.field for g in report.gaps_pending],
                },
            )
        )

    def _export_competitor_json(self, report: CompetitorReport, session_id: str) -> Path | None:
        """设计文档 28：config.report.export_json 开启时导出 <data_dir>/reports/competitor/<竞品>.json。

        结构化副本与 .md 同目录同名；成功后在报告正文末尾追加"已导出 JSON 路径"提示。
        失败仅告警不影响主流程；成功返回落盘路径。
        """
        if not self._config.report.export_json:
            return None
        try:
            path = export_competitor_json(report, self._config.report.output_dir)
        except Exception:
            logger.warning("JSON 导出失败（竞品: %s）: ", report.competitor.name, exc_info=True)
            return None
        try:
            note = f"\n> 结构化数据已导出: `{path}`\n"
            if report.markdown_report and note.strip() not in report.markdown_report:
                report.markdown_report = report.markdown_report.rstrip() + "\n" + note
        except Exception:
            logger.warning("竞品 JSON 导出提示追加失败: %s", report.competitor.name, exc_info=True)
        return path

    def _export_comparison_json(self, report: ComparisonReport) -> Path | None:
        """设计文档 28：比较报告导出 <data_dir>/reports/comparison/<names>.json（品类矩阵）。"""
        if not self._config.report.export_json:
            return None
        try:
            path = export_comparison_json(report, self._config.report.comparison_dir)
        except Exception:
            logger.warning("对比矩阵 JSON 导出失败: ", exc_info=True)
            return None
        try:
            note = f"\n> 结构化矩阵已导出: `{path}`\n"
            if report.markdown_report and note.strip() not in report.markdown_report:
                report.markdown_report = report.markdown_report.rstrip() + "\n" + note
        except Exception:
            logger.warning("对比矩阵 JSON 导出提示追加失败: %s", report.competitors, exc_info=True)
        return path

    def report_diff(self, prev: CompetitorReport, cur: CompetitorReport) -> list[Alert]:
        """两份报告维度级 diff → 竞品异动告警（复用 TimelineMemory.diff 映射为 Alert）。"""
        return _diff_to_alerts(prev, cur)

    def run_scheduled(
        self,
        competitors: list[str] | None = None,
        alert_sink: AlertSink | None = None,
    ) -> list[CompetitorReport]:
        """定时调度轮（设计文档 28 §3.2）：对跟踪竞品执行一次调度轮。

        - 目标竞品：显式传入或归档里的跟踪竞品（去重、跳过对比/发现聚合会话）；
        - 过滤未过期（freshness 内）的竞品，仅重爬过期的；
        - 逐个 analyze（含 JSON 导出），与上次报告 diff 产出异动告警 → AlertSink；
        - 单竞品失败不回滚整体。

        调用时机由外部调度器（cron）控制，本方法只保证"过期才重爬"语义。
        """
        sink = alert_sink or ConsoleAlertSink()
        names = list(competitors) if competitors else self._tracked_competitors()
        if not names:
            return []
        ttl = dict(self._config.freshness.dimension_ttl_days)
        refreshed: list[CompetitorReport] = []
        for name in names:
            if not self._stale_for_schedule(name, ttl):
                continue
            # 先取上次快照作 diff 基线，再重爬（analyze 会在 _record_timeline 里覆盖快照）
            prev = self._timeline.report_for(name)
            self._emit(
                ProgressEvent(
                    event="phase_start",
                    phase="schedule",
                    message=f"定时重爬过期竞品: {name}",
                )
            )
            report = self.analyze(name, session_id=f"schedule_{uuid.uuid4().hex[:8]}")
            refreshed.append(report)
            if prev is not None:
                for alert in self.report_diff(prev, report):
                    sink.emit(alert)
            self._emit(
                ProgressEvent(
                    event="refreshed",
                    phase="schedule",
                    message=f"已刷新 {name}",
                    payload={"competitor": name},
                )
            )
        return refreshed

    def _tracked_competitors(self) -> list[str]:
        """归档里的跟踪竞品（每个竞品取最新会话，跳过 " / " 的聚合/对比会话）。"""
        if self._memory is None:
            return []
        latest: dict[str, object] = {}
        for s in self._memory.list_sessions():
            comp = getattr(s, "competitor_name", "")
            if not comp or " / " in comp:
                continue
            if comp not in latest:
                latest[comp] = s
        return list(latest)

    def _stale_for_schedule(self, name: str, ttl: dict[str, int]) -> bool:
        """竞品最新归档会话的 stale 判定：无归档 → 视为需重爬；freshness 内 → 跳过。"""
        if self._memory is None:
            return True
        sessions = self._memory.list_sessions(name)
        if not sessions:
            return True
        raw = getattr(sessions[0], "raw", None) or {}
        return bool(stale_under_ttl(raw, ttl)) or not raw

    def _last_report_for(self, name: str) -> CompetitorReport | None:
        """最近一次时间线快照重建为 CompetitorReport（告警 diff 的 prev；无则 None）。"""
        return self._timeline.report_for(name)

    def analyze_react(self, task: str, session_id: str | None = None) -> str:
        """ReAct 交互入口（设计文档 40/49）：Lead 编排循环，返回结论文本。

        与 analyze() 同源（make_plan 首步 + delegate + 复核工具），仅返回裸文本。
        """
        _, result = self._run_react_loop(task, session_id)
        return result.answer

    def analyze_react_report(self, task: str, session_id: str | None = None) -> CompetitorReport:
        """ReAct 结构化入口（设计文档 43 §2.3 兼容）：产物入 CompetitorReport。

        复用与 analyze() 同源的 Lead 编排；结论文本按 REPORT_SCHEMA JSON
        组装为多维度报告，非 JSON 降级为单 react 维度（react_report.assemble）。
        """
        loop, result = self._run_react_loop(task, session_id)
        terminal = (
            "cancelled"
            if result.cancelled
            else ("partial" if result.budget_exhausted else "success")
        )
        return react_report.assemble(
            lead_answer=result.answer,
            competitor=self._lead_competitor(task, loop.plan),
            loop_plan=loop.plan,
            transcript=result.transcript,
            builder=self._builder,
            terminal_state=terminal,
        )

    def _run_react_loop(self, task: str, session_id: str | None) -> tuple[ReactLoop, ReactRunResult]:
        """构建 Lead ReactLoop 并运行；会话收尾统一回收子 Agent 线程池。

        DelegateRunner 挂在 loop 实例（而非 self），避免并行 analyze()（compare
        并发）共享 self._delegate_runner 时互相 shutdown 彼此的线程池。
        """
        loop = self._react_loop(task, session_id)
        try:
            result = loop.run_with_result(task)
        finally:
            runner = getattr(loop, "_delegate_runner", None)
            if runner is not None:
                runner.shutdown()
        if result.steps:
            self._budget.record_iteration(cost=0.01 * result.steps)
        return loop, result

    def _run_langgraph_engine(
        self, task: str, session_id: str | None
    ) -> tuple[dict | None, str, list[dict]]:
        """LangGraph 引擎路径（设计文档 51 §2.2）：StateGraph 编排，其余全复用。

        与 ``_run_react_loop`` 同形返回 ``(plan, answer, transcript)``：
        LLM/工具/记忆/RAG/事件/报告出口与自研引擎逐位一致（对照实验控变量），
        唯一变量是编排层（StateGraph plan→Send fan-out→aggregate→report）。
        取消/预算/checkpoint 不做图级对齐（§1.2 差异化结论）；
        预算记账以 transcript 记录数近似步数（同 0.01/步 口径）。
        """
        from competitor_agent.agent.langgraph_engine import run_langgraph

        llm = self._llm or LLMClient(tracer=self._tracer)
        lead_competitor = self._react_competitor(task)

        def _subagent_run(name: str, sub_task: str) -> ReactRunResult:
            # 子 Agent 运行时与自研路径同工厂（独立预算/共享取消/记忆/RAG/事件）
            budget = IterationBudget(
                max_iterations=6,
                cost_limit=self._budget.cost_limit,
                diminishing_threshold=0,
            )
            return build_subagent(
                name,
                llm,
                config=self._config,
                web_extract=self._web_extract_for(lead_competitor.name, name),
                session_id=session_id,
                budget=budget,
                memory_context_fn=lambda t: self._memory_ctx_for(lead_competitor.name, t),
                rag_fn=lambda t: self._rag_ctx_for(lead_competitor.name, t),
                event_sink=self._event_sink,
                obs_max_chars=self._config.collector.max_content_chars,
                max_steps=6,
                tracer=self._tracer,  # 设计文档 54：子 Agent span
                max_parallel_tool_calls=self._max_parallel_tool_calls,
            ).run_subagent(sub_task)

        # Lead 系统提示与自研路径同（设计文档 60：单协议，无工具描述/格式说明）
        prompt_dispatcher = build_react_dispatcher(
            config=self._config,
            web_extract=self._react_web_extract,
            exclude=("analyze_competitor",),
            extra_tools={"make_plan": build_make_plan_tool()},
            tracer=self._tracer,
        )
        base_prompt = ReactAgent(
            llm=llm, dispatcher=prompt_dispatcher
        ).build_system_prompt(
            instructions=build_lead_system_prompt()
        )
        plan, answer, transcript = run_langgraph(
            task,
            llm=llm,
            make_plan_fn=build_make_plan_tool(),
            subagent_run=_subagent_run,
            registry=get_subagent_registry(),
            event_sink=self._event_sink,
            session_id=session_id,
            memory_ctx_fn=self._react_memory_context,
            rag_fn=self._react_rag_context,
            system_prompt=base_prompt,
        )
        if transcript:
            self._budget.record_iteration(cost=0.01 * len(transcript))
        return plan, answer, transcript

    def _react_loop(self, task: str, session_id: str | None) -> ReactLoop:
        """组装 Lead ReactLoop（设计文档 49 §3.5/3.6）：plan-first + delegate + 复核工具。

        - ``exclude=("analyze_competitor",)``：防递归调用 analyze()；
        - ``extra_tools``：make_plan（首步强制）+ delegate（后台并发委派）+ 复核工具；
        - 子 Agent 运行时经 ``DelegateRunner`` 后台线程池执行，共享取消/记忆/RAG。
        """
        if not self._config.subagents.enabled:
            from competitor_agent.interfaces.exceptions import CompetitorAgentError

            raise CompetitorAgentError("subagents.enabled=false 时 analyze() 主路径不可用（设计文档 49）")
        # 设计文档 62 §3.8：delegate 并发硬上限 = execution.max_parallel_subagents（不再自决）
        max_concurrent = self._config.execution.max_parallel_subagents
        timeout_seconds = self._config.subagents.timeout_seconds
        lead_competitor = self._react_competitor(task)
        # 设计文档 62 §3.6/§3.9：子 Agent 沿用 react_agent 默认压缩保留步数；
        # Lead 编排会话用独立 lead.max_history_steps（候选委派回填更长）
        agent_max_history_steps = self._config.agent.max_history_steps
        lead_max_history_steps = self._config.lead.max_history_steps
        # 设计文档 56 M1/M2：Lead 级共享状态——plan 懒绑定 cell + 已核验事实 pinned 清单
        plan_box: dict[str, ReactLoop | None] = {"loop": None}
        pinned_facts: list[str] = []

        def _lead_competitor_now() -> str:
            """competitor 懒绑定：make_plan 落地后经 loop.plan 回填，落地前空串（全局检索）。"""
            loop = plan_box["loop"]
            if loop is not None and loop.plan:
                return str(loop.plan.get("competitor") or "")
            return ""

        def _collect_pinned(rec: dict) -> None:
            pinned_facts.extend(extract_verified_facts(rec))

        def _subagent_loop(name: str, sub_task: str) -> ReactLoop:
            # 子 Agent 步数由其 max_steps 兜底；diminishing_threshold=0 关闭"边际递减"
            # 启发（ReAct 恒传 delta_tokens=0，否则第 3 步后必然误判预算耗尽）
            budget = IterationBudget(
                max_iterations=6,
                cost_limit=self._budget.cost_limit,
                diminishing_threshold=0,
            )
            return build_subagent(
                name,
                self._llm or LLMClient(tracer=self._tracer),
                config=self._config,
                web_extract=self._web_extract_for(lead_competitor.name, name),
                extra_tools={
                    # 设计文档 56 M1①：子 Agent kb_recall 按（竞品×维度）绑定
                    "kb_recall": self._build_kb_recall(lambda: lead_competitor.name, name),
                },
                session_id=session_id,
                budget=budget,
                memory_context_fn=lambda t: self._memory_ctx_for(lead_competitor.name, t),
                rag_fn=lambda t: self._rag_ctx_for(lead_competitor.name, t),
                event_sink=self._event_sink,
                obs_max_chars=self._config.collector.max_content_chars,
                max_steps=6,
                tracer=self._tracer,  # 设计文档 54：子 Agent tool.call span
                max_history_steps=agent_max_history_steps,
                max_parallel_tool_calls=self._max_parallel_tool_calls,
            )

        runner = DelegateRunner(
            runtime_factory=lambda name: SubagentRuntime(
                name=name,
                run=lambda sub_task: _subagent_loop(name, sub_task).run_subagent(sub_task),
            ),
            max_concurrent=max_concurrent,
            timeout_seconds=timeout_seconds,
            tracer=self._tracer,  # 设计文档 54：跨线程 subagent span
        )
        extra_tools: dict[str, Callable[..., str] | ToolSpec] = {
            "make_plan": build_make_plan_tool(),
            "delegate": make_delegate_tool(runner, registry=get_subagent_registry()),
            # 设计文档 62 §3.3：Lead 聚合 DISCOVERY/COMPARE 候选结论，产出市场格局核心结论
            "aggregate_report": make_aggregate_tool(),
            # 设计文档 56 M1①：Lead kb_recall（competitor 懒绑定，plan 落地前全局检索）
            "kb_recall": self._build_kb_recall(_lead_competitor_now),
        }
        if self._config.tools.validate_facts:
            extra_tools["validate_facts"] = build_validate_facts_tool()
        if self._config.tools.detect_conflict:
            extra_tools["detect_conflict"] = build_detect_conflict_tool()
        if self._config.tools.check_freshness:
            extra_tools["check_freshness"] = build_check_freshness_tool(self._check_freshness)
        if self._config.tools.select_source:
            extra_tools["select_source"] = build_select_source_tool(self._select_source)

        dispatcher = build_react_dispatcher(
            config=self._config,
            web_extract=self._lead_web_extract(_lead_competitor_now),
            exclude=("analyze_competitor",),
            extra_tools=extra_tools,
            tracer=self._tracer,  # 设计文档 54：Lead tool.call span
        )
        agent = ReactAgent(
            llm=self._llm or LLMClient(tracer=self._tracer),
            dispatcher=dispatcher,
            max_parallel_tool_calls=self._max_parallel_tool_calls,
        )
        # Lead 步数上限：默认 lead.max_orchestration_steps（设计文档 62 §3.8，编排场景可容纳）；
        # 用户显式传 max_iterations 时以其为准（含 0，预算耗尽→partial，设计文档 14 承诺）；
        # diminishing_threshold=0 关闭"边际递减"启发
        # （ReAct 恒传 delta_tokens=0，否则第 3 步后必然误判预算耗尽）
        lead_max = self._budget.max_iterations if self._budget.max_iterations is not None else _LEAD_MAX_STEPS
        budget = IterationBudget(
            max_iterations=lead_max,
            cost_limit=self._budget.cost_limit,
            diminishing_threshold=0,
        )
        loop = ReactLoop(
            agent,
            max_steps=self._config.lead.max_orchestration_steps,
            event_sink=self._event_sink,
            session_id=session_id,
            budget=budget,
            memory_context_fn=self._react_memory_context,
            rag_fn=self._react_rag_context,
            obs_max_chars=self._config.collector.max_content_chars,
            system_prompt_override=build_lead_system_prompt(),
            plan_first=True,
            max_history_steps=lead_max_history_steps,
            pinned_facts=pinned_facts,
            on_step=_collect_pinned,
        )
        # 收尾 shutdown 用（挂 loop 实例而非 self，避免并行 analyze 互相误杀线程池）
        loop._delegate_runner = runner
        plan_box["loop"] = loop  # kb_recall/Lead 摄入的 competitor 懒绑定数据源
        return loop

    def _react_competitor(self, task: str) -> Competitor:
        """从任务解析竞品（注册表命中带官方源；未知竞品退化为裸名）。"""
        from competitor_agent.core.competitor_registry import resolve_competitor

        try:
            name = parse_task(task, llm=self._llm, use_llm=self._use_llm).primary_competitor
        except Exception:  # noqa: BLE001 — 解析失败不影响 ReAct 产物
            name = ""
        if name and name != "unknown":
            try:
                competitor = resolve_competitor(name)
            except ValueError:
                competitor = None
            if competitor is not None:
                return competitor
        return Competitor(name=name or "unknown")

    def _lead_competitor(self, task: str, plan: dict | None) -> Competitor:
        """报告竞品：优先用 plan 的 competitor（注册表命中带官方源），否则从任务解析。"""
        from competitor_agent.core.competitor_registry import resolve_competitor

        name = str((plan or {}).get("competitor") or "").strip()
        if name:
            try:
                competitor = resolve_competitor(name)
                if competitor is not None:
                    return competitor
            except Exception:  # noqa: BLE001 — 注册表解析失败退化为裸名
                logger.debug("注册表解析竞品 %s 失败，退化为裸名", name)
            return Competitor(name=name)
        return self._react_competitor(task)

    def _react_memory_context(self, task: str) -> str:
        """记忆召回（设计文档 35 recent_context）：失败静默降级。"""
        if self._memory is None:
            return ""
        return self._memory_ctx_for(self._react_competitor(task).name, task)

    def _memory_ctx_for(self, competitor: str, task: str) -> str:
        """按已知竞品名做记忆召回（子 Agent 复用，避免逐子 Agent 重复解析任务）。"""
        if self._memory is None or not competitor or competitor == "unknown":
            return ""
        try:
            return "\n".join(self._memory.recent_context(competitor, top_k=3, query=task))
        except Exception:
            logger.warning("ReAct 记忆召回失败: %s", competitor, exc_info=True)
            return ""

    def _react_rag_context(self, task: str) -> str:
        """RAG 检索（与 GapExecutor._retrieve_rag 同口径）：失败静默降级。"""
        if self._retriever is None:
            return ""
        return self._rag_ctx_for(self._react_competitor(task).name, task)

    def _rag_ctx_for(self, competitor: str, task: str) -> str:
        """按已知竞品名做 RAG 检索（子 Agent 复用，避免逐子 Agent 重复解析任务）。"""
        if self._retriever is None:
            return ""
        try:
            chunks = self._retriever.retrieve(
                query=task, competitor=competitor, dimension="", top_k=5
            )
        except Exception:  # 检索失败不影响推理
            logger.warning("ReAct RAG 检索失败: %s", competitor, exc_info=True)
            return ""
        if not chunks:
            return ""
        lines = []
        for c in chunks:
            src = f"（来源: {c.source_url}）" if c.source_url else ""
            lines.append(f"- [{c.competitor}/{c.dimension}]{src} {c.text[:300]}")
        return "\n".join(lines)

    def _react_web_extract(self, url: str) -> str:
        """ReAct 工具：真实抓取给定 URL 的页面文本（失败返回可读信息）。

        抓取前过 URL 守卫（设计文档 41）：私网/保留地址拒绝，返回可读原因供回灌自恢复。
        """
        try:
            if self._config.collector.block_private_urls:
                url = guard_http_url(url)
        except URLError as exc:
            return f"URL 被安全守卫拦截: {exc}"
        try:
            obs = self._extractor.fetch(
                InfoGap(field="web"),
                SourceContext(competitor_name="", query="web", kwargs={"url": url}),
            )
        except DataSourceUnavailableError as exc:
            return f"抓取失败: {exc}"
        max_chars = self._config.collector.max_content_chars
        return (obs.raw_text or "").strip()[:max_chars] or "（页面无文本内容）"

    def _web_extract_for(self, competitor: str, dimension: str) -> Callable[[str], str]:
        """子 Agent 专用 web_extract：抓取后按（竞品×维度）摄入知识库（RAG 写侧）。

        设计文档 30：分析中采集到的原文即知识库增量，后续分析与追问可检索复用。
        抓取失败的占位文本（守卫拦截/抓取失败）不摄入，避免污染知识库。
        """

        def _extract(url: str) -> str:
            text = self._react_web_extract(url)
            self._ingest_fetched(competitor, dimension, url, text)
            return text

        return _extract

    def _lead_web_extract(self, competitor_fn: Callable[[], str]) -> Callable[[str], str]:
        """Lead 专用 web_extract（设计文档 56 M1②）：抓取成功后摄入知识库通用域。

        补齐 Lead 摄入缺口（此前只有子 Agent 摄入，Lead 抓的内容取回工具够不到）。
        competitor 懒绑定（make_plan 落地后经 loop.plan 回填），落地前摄入
        ``dimension="web"`` 通用域；守卫拦截/抓取失败/空文本占位不摄入（沿用
        ``_ingest_fetched`` 既有纪律）。闭包按 loop 构造（不挂 self），避免并行
        analyze 互相串 competitor。
        """

        def _extract(url: str) -> str:
            text = self._react_web_extract(url)
            self._ingest_fetched(competitor_fn(), "web", url, text)
            return text

        return _extract

    def _build_kb_recall(
        self,
        competitor_fn: Callable[[], str],
        dimension: str = "",
    ) -> ToolSpec:
        """kb_recall 闭包工厂（设计文档 56 M1①）：循环内知识库取回工具。

        走 extra_tools（不进 TOOLS/TOOL_SPECS，MCP 工具面零变化）；复用既有
        Retriever 混合检索，零新存储/新依赖。知识库为空/未装配时返回可读信息
        （工具面稳定，不随状态缺 tool）。``competitor_fn`` 懒绑定：Lead 在
        make_plan 落地前以空串全局检索（同竞品优先过滤对空串自然失效）。
        """

        def kb_recall(query: str) -> str:
            if self._retriever is None:
                return "知识库暂无可检索内容（检索器未装配）。"
            try:
                chunks = self._retriever.retrieve(
                    query=str(query), competitor=competitor_fn(), dimension=dimension, top_k=5
                )
            except Exception:
                logger.warning("kb_recall 检索失败", exc_info=True)
                return "知识库检索失败，请改用其他方式获取信息。"
            if not chunks:
                return "知识库暂无可检索内容。"
            lines = []
            for c in chunks:
                src = f"（来源: {c.source_url}）" if c.source_url else ""
                lines.append(f"- [{c.competitor}/{c.dimension}]{src} {c.text[:300]}")
            return "\n".join(lines)[: self._config.collector.max_content_chars]

        return ToolSpec(
            name="kb_recall",
            func=kb_recall,
            description="从知识库取回被折叠步骤的完整内容；仅当需要回溯旧步详情时使用",
            params_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )

    def _ingest_fetched(self, competitor: str, dimension: str, url: str, text: str) -> None:
        """采集原文 → 知识库摄入（幂等：chunk_id 由内容哈希决定）。"""
        if self._ingester is None:
            return
        if not text or text.startswith(("URL 被安全守卫拦截", "抓取失败", "（页面无文本内容）")):
            return
        try:
            self._ingester.ingest(competitor, dimension, text, source_url=url)
        except Exception:  # noqa: BLE001 — 摄入失败不影响采集/分析
            logger.debug("RAG 摄入跳过: %s/%s %s", competitor, dimension, url)

    # ── 复核工具提供方（设计文档 49：代码确定性兜底，不进 LLM 决策）────────

    def _check_freshness(self, competitor: str, dimensions: list[str]) -> dict[str, str]:
        """维度新鲜度判定：读归档年龄（ReportFreshness.dimension_ages）→ {dim: stale/fresh/skip}。"""
        decisions: dict[str, str] = {}
        if self._memory is None:
            return decisions
        try:
            sessions = self._memory.list_sessions(competitor)
            ages: dict[str, float] = {}
            if sessions:
                raw = getattr(sessions[0], "raw", None) or {}
                freshness = ReportFreshness.from_dict(raw.get("freshness"))
                if freshness is not None:
                    ages = dict(freshness.dimension_ages)
        except Exception:
            logger.warning("check_freshness 归档读取失败: %s", competitor, exc_info=True)
            return decisions
        ttl = dict(self._config.freshness.dimension_ttl_days)
        for dim in dimensions:
            age = ages.get(dim)
            if age is None:
                decisions[dim] = "skip"  # 无归档年龄 → 正常采集
            elif age <= float(ttl.get(dim, 30)):
                decisions[dim] = "fresh"
            else:
                decisions[dim] = "stale"
        return decisions

    def _select_source(self, competitor: str, dimension: str) -> list[str]:
        """确定性候选源：注册表 official_links + 常见路径探测（原 SourceSelector 语义）。"""
        from urllib.parse import urlsplit

        from competitor_agent.core.competitor_registry import resolve_competitor

        links: dict[str, str] = {}
        try:
            comp = resolve_competitor(competitor)
            links = dict(comp.official_links or {}) if comp is not None else {}
        except Exception:
            logger.warning("select_source 注册表解析失败: %s", competitor, exc_info=True)
        candidates: list[str] = []
        key = {"pricing": "pricing", "roadmap": "changelog", "feature": "docs"}.get(dimension)
        if key and links.get(key):
            candidates.append(links[key])
        home = links.get("home")
        if home and home not in candidates:
            candidates.append(home)
        # 常见路径探测（确定性）：官方站点按维度拼接，优先级最低
        base = home or (candidates[0] if candidates else "")
        if base:
            try:
                host = urlsplit(base).netloc
                path = {
                    "pricing": "/pricing",
                    "feature": "/features",
                    "roadmap": "/changelog",
                    "ecosystem": "/integrations",
                    "performance": "/benchmarks",
                }.get(dimension)
                if path:
                    candidate = f"https://{host}{path}"
                    if candidate not in candidates:
                        candidates.append(candidate)
            except Exception:  # noqa: BLE001 — 路径探测失败不影响已得候选
                logger.debug("探测 %s 的 %s 路径失败，跳过", base, dimension)
        return candidates

    # ── 记忆写侧（设计文档 49：唯一沉淀点）───────────────────────────────

    def _record_memory_success(self, report: CompetitorReport, transcript: list[dict]) -> None:
        """记忆沉淀（唯一写侧）：每维度取 transcript 首个 URL 源 → skill/outcome/pattern。

        transcript 步（tool/args/result_brief/url）中匹配到该维度或 delegate 批量
        回填的首个 URL 作为来源键（L4 源成功率按 URL 计量）；无则回退报告证据 URL。
        """
        if self._memory is None:
            return
        competitor = report.competitor.name
        for r in report.dimension_results:
            source = self._first_url_for(transcript, r.dimension)
            if not source and r.evidence:
                source = r.evidence[0].url
            if not source:
                continue
            self._memory.record_skill(
                Skill(competitor_name=competitor, gap_field=r.dimension, source_name=source, success=True)
            )
            self._memory.record_outcome(source, True)
            # 设计文档 35：沉淀进化经验（成功模式）
            self._memory.note_pattern(
                competitor,
                r.dimension,
                pattern=f"缺口 {r.dimension} 由源 {source} 有效",
                outcome="success",
            )

    @staticmethod
    def _first_url_for(transcript: list[dict], dimension: str) -> str:
        """transcript 中命中维度的首个 URL，供记忆写侧。

        delegate 批量回填按子结果块切分，避免全部维度都指向首块 URL。
        """
        for step in transcript or []:
            if not isinstance(step, dict):
                continue
            url = str(step.get("url") or "")
            blob = f"{step.get('result_brief') or ''} {step.get('args') or ''}"
            if step.get("tool") == "delegate":
                section = _delegate_section_url(str(step.get("result_brief") or ""), dimension)
                if section:
                    return section
                continue
            if url and dimension in blob:
                return url
        return ""

    def _save_checkpoint_for_resume(
        self, session_id: str, task: str, report: CompetitorReport
    ) -> None:
        """取消时保留 checkpoint（设计文档 14）：未关闭缺口 + 已完成维度，供 /resume 续跑。"""
        gaps = [
            InfoGap(field=g.field, priority=g.priority, status=GapStatus.OPEN)
            for g in report.gaps_pending
        ]
        save_checkpoint(
            session_id=session_id,
            task=task,
            competitor_name=report.competitor.name,
            gaps=gaps,
            dimension_results=report.dimension_results,
            iterations_used=self._budget.iteration_count,
            max_iterations=self._budget.max_iterations,
            cost_used=self._budget.total_cost,
            cost_limit=self._budget.cost_limit,
            sources_tried=[e.url for r in report.dimension_results for e in r.evidence],
        )

    # ── team 兼容薄包装（设计文档 49：内部固定流水线删除，保留入口）────────

    def analyze_team(
        self,
        task: str,
        session_id: str | None = None,
        max_retries: int = 1,
    ) -> CompetitorReport:
        """历史兼容入口：委托 analyze()（Lead ReAct 编排，设计文档 49）。"""
        if max_retries != 1:
            logger.warning("analyze_team 的 max_retries 参数已废弃，忽略")
        return self.analyze(task, session_id=session_id)

    async def analyze_team_async(
        self,
        task: str,
        session_id: str | None = None,
        max_retries: int = 1,
        max_parallel: int = 4,
    ) -> CompetitorReport:
        """历史兼容异步入口：线程池包装 analyze()（签名不变，设计文档 49）。"""
        if max_retries != 1 or max_parallel != 4:
            logger.warning("analyze_team_async 的 max_retries/max_parallel 参数已废弃，忽略")
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.analyze, task, None, "team", session_id)

    # ── M4: 流式分析 ──────────────────────────────────────────────────

    async def analyze_stream(self, task: str, session_id: str | None = None) -> AsyncIterator[ProgressEvent]:
        """流式分析：逐条 yield ProgressEvent（供 Web SSE 消费）"""
        sid = session_id or f"sess_{uuid.uuid4().hex[:8]}"

        yield ProgressEvent(
            event="session_started",
            phase="init",
            message=f"会话 {sid} 已启动",
            payload={"session_id": sid},
        )

        import asyncio

        loop = asyncio.get_running_loop()
        report = await loop.run_in_executor(None, self.analyze, task, None, "team", sid)

        yield ProgressEvent(
            event="report",
            phase="report",
            progress=1.0,
            message=f"报告生成完成，{len(report.dimension_results)} 个维度",
            payload={
                "competitor": report.competitor.name,
                "terminal_state": report.terminal_state,
                "overall_confidence": report.overall_confidence,
            },
        )

        # 归档会话（统一 raw schema，见问题 18）
        if self._memory is not None:
            self._memory.archive_session(
                AnalysisSession(
                    task=task,
                    competitor_name=report.competitor.name,
                    session_id=sid,
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

    # ── M4: 中断与断点续跑 ───────────────────────────────────────────

    def cancel(self, session_id: str) -> None:
        """请求取消运行中的分析会话"""
        set_cancel(session_id)
        logger.info("已请求取消会话: %s", session_id)

    def resume(self, session_id: str) -> CompetitorReport:
        """从 checkpoint 恢复：预置已完成维度，未关闭缺口合成 Lead ReAct 续跑任务。"""
        cp = load_checkpoint(session_id)
        if cp is None:
            raise ValueError(f"会话 {session_id} 无 checkpoint，无法恢复")
        # resume 是显式新调用：清除前次取消标志，否则 analyze() 立即判取消、续跑空转
        clear_cancel(session_id)
        logger.info("从 checkpoint 恢复会话: %s (%d gaps)", session_id, len(cp.gaps))

        # 1. 重建竞品与缺口状态（用注册表恢复官方源）
        from competitor_agent.core.competitor_registry import resolve_competitor

        competitor = None
        if cp.competitor_name and cp.competitor_name != "unknown":
            try:
                competitor = resolve_competitor(cp.competitor_name)
            except ValueError:
                from competitor_agent.core.competitor_registry import canonicalize

                competitor = Competitor(name=canonicalize(cp.competitor_name))
        else:
            competitor = Competitor(name=cp.competitor_name)
        gaps = self._reconstruct_gaps_from_checkpoint(cp.gaps)

        # 2. 预置已完成维度（不重跑已关闭缺口）
        completed: list[DimensionResult] = [
            checkpoint_to_report._result_from_dict(r) if hasattr(checkpoint_to_report, '_result_from_dict') else
            DimensionResult(
                dimension=r["dimension"],
                summary=r.get("summary", ""),
                details=r.get("details", {}),
                confidence=r.get("confidence", 0.0),
                evidence=[
                    SourceEvidence(
                        source_name=e["source_name"],
                        url=e.get("url", ""),
                        access_time=e.get("access_time", ""),
                        content_hash=e.get("content_hash", ""),
                        trust_level=e.get("trust_level", 0.5),
                    )
                    for e in r.get("evidence", [])
                ],
                timestamp=r.get("timestamp", ""),
                status=ResultStatus(r.get("status", "partial")),
            )
            for r in cp.dimension_results
        ]

        # 3. 未关闭缺口 → 合成 Lead ReAct 续跑任务（已完成维度由 checkpoint 预置）
        open_gaps = [g for g in gaps if not g.is_closed]
        if open_gaps:
            task = self._resume_task(cp.task, [g.field for g in open_gaps])
            resumed = self.analyze(task, session_id=session_id)
            by_dim = {r.dimension: r for r in completed}
            for r in resumed.dimension_results:
                by_dim[r.dimension] = r
            results = list(by_dim.values())
            # 续跑后仍未产出的缺口（交集）留作 pending
            produced = {r.dimension for r in results}
            pending = [
                g for g in resumed.gaps_pending
                if g.field not in produced and g.field in {og.field for og in open_gaps}
            ]
            terminal = resumed.terminal_state
        else:
            results = completed
            pending = []
            terminal = "success"
            delete_checkpoint(session_id)

        report = self._builder.build(
            competitor=competitor,
            results=results,
            gaps_pending=pending,
            terminal_state=terminal,
        )

        if is_cancelled(session_id):
            logger.info("会话 %s 续跑中再次取消，返回部分结果", session_id)
            self._emit(ProgressEvent(event="cancelled", phase="report", message="续跑已取消"))
            return CancelledResult(
                competitor=report.competitor,
                dimension_results=report.dimension_results,
                overall_score=report.overall_score,
                overall_confidence=report.overall_confidence,
                gaps_pending=report.gaps_pending,
                markdown_report=report.markdown_report,
                terminal_state="cancelled",
                created_at=report.created_at,
                cancelled=True,
            )

        self._record_timeline(report)
        self._emit(ProgressEvent(event="report", phase="report", progress=1.0, message="续跑完成"))
        return report

    @staticmethod
    def _resume_task(base_task: str, dimensions: list[str]) -> str:
        """把待续跑维度声明进任务文本，供 Lead 重排（已完成维度由 checkpoint 预置）。"""
        dim_text = "、".join(dimensions) or "全部维度"
        return f"{base_task}（续跑：请补齐维度 {dim_text}，已完成维度直接复用）"

    @staticmethod
    def _reconstruct_gaps_from_checkpoint(gaps_data: list[dict]) -> list[InfoGap]:
        """从 checkpoint gap 字典列表重建 InfoGap 对象（保留 status/confidence/evidence）。"""
        gaps = []
        for g in gaps_data:
            gap = InfoGap(
                field=g["field"],
                priority=g.get("priority", 5),
                confidence=g.get("confidence", 0.0),
                sources_tried=g.get("sources_tried", []),
                status=GapStatus(g.get("status", "open")),
            )
            for ev in g.get("evidence", []):
                gap.add_evidence(
                    SourceEvidence(
                        source_name=ev.get("source_name", ""),
                        url=ev.get("url", ""),
                        content_hash=ev.get("content_hash", ""),
                        trust_level=ev.get("trust_level", 0.5),
                    )
                )
            gaps.append(gap)
        return gaps

    # ── M4: 历史查询 ──────────────────────────────────────────────────

    def get_history(self, competitor: str | None = None) -> list[CompetitorReport]:
        """查询历史分析报告

        Args:
            competitor: 竞品名称（可选，留空返回全部）
        Returns:
            历史报告列表
        """
        if self._memory is None:
            return []

        sessions = self._memory.list_sessions(competitor)

        reports: list[CompetitorReport] = []
        for s in sessions:
            raw = s.raw if hasattr(s, "raw") else {}
            reports.append(
                CompetitorReport(
                    competitor=Competitor(name=s.competitor_name),
                    markdown_report=str(raw.get("markdown_report", "")),
                    terminal_state=str(raw.get("terminal_state", "")),
                    created_at=s.created_at,
                )
            )
        return reports

    # ── M5: 会话历史 / 对比 / 继续分析 ────────────────────────────────

    def _disambiguate_with_history(
        self,
        task: str,
        conversation_history: list[ChatMessage] | None,
    ) -> str:
        """结合会话历史消歧：上一轮已分析的竞品可作为本轮上下文。

        若任务解析出的竞品是 unknown（相对指代如"再对比下 Windsurf"），
        尝试从历史消息中提取最近竞品，拼成可解析的任务文本。
        解析失败（LLM 不可用）直接返回原 task——消歧是可选增强（设计文档 47）。
        """
        if not conversation_history:
            return task
        try:
            parsed = parse_task(task, llm=self._llm, use_llm=self._use_llm)
        except Exception:
            logger.warning("历史消歧任务解析失败，返回原 task", exc_info=True)
            return task
        if parsed.primary_competitor != "unknown":
            return task
        last_competitor = self._last_competitor_from_history(conversation_history)
        if last_competitor:
            return f"{task}（承接上文：{last_competitor}）"
        return task

    @staticmethod
    def _last_competitor_from_history(history: list[ChatMessage]) -> str:
        """从历史消息中提取最近提到的竞品规范名"""
        from competitor_agent.core.competitor_registry import COMPETITOR_REGISTRY

        for message in reversed(history):
            content = (message.content or "").lower()
            for canon, competitor in COMPETITOR_REGISTRY.items():
                if canon in content or any(a in content for a in competitor.aliases):
                    return competitor.name
        return ""

    def run(
        self,
        task: str,
        *,
        session_id: str | None = None,
    ) -> CompetitorReport | ComparisonReport:
        """统一入口（设计文档 62 §3.5/§3.7）：取代 web/CLI/MCP 各自的分派 if-else。

        parse_task（LLM）→ 按语义路由：DISCOVERY→discover 语义、COMPARE→N 向对比、
        其余→单竞品 analyze。resolution 作为上下文标注透传，入口不再写重复分派。
        """
        task = sanitize_task(task)
        parsed = parse_task(task, llm=self._llm, use_llm=self._use_llm)
        if parsed.resolution == ResolutionDecision.DISCOVERY:
            return self._run_discovery(task, session_id=session_id)
        if parsed.is_compare and len(parsed.competitors) >= 2:
            return self._run_compare(list(parsed.competitors), session_id=session_id)
        return self.analyze(task, session_id=session_id)

    def discover(self, task: str) -> ComparisonReport:
        """兼容保留（设计文档 62 §3.5）：= run(task) 的 DISCOVERY 语义路径（deprecated 告警）。"""
        logger.warning("discover() 已废弃（历史兼容）：请改用 run() 统一入口")
        return self._run_discovery(task)

    def compare(self, *competitors: str) -> ComparisonReport:
        """兼容保留（设计文档 62 §3.5）：= run(task) 的 COMPARE 语义路径（deprecated 告警）。

        兼容旧签名 compare(a, b=None)：单个参数会被解析（"对比 A 和 B" / "A vs B"）；
        多个参数逐个作为竞品名处理。
        """
        logger.warning("compare() 已废弃（历史兼容）：请改用 run() 统一入口")
        names: list[str] = []
        if len(competitors) == 1:
            parsed = parse_task(competitors[0], llm=self._llm, use_llm=self._use_llm)
            names = list(parsed.competitors)
        else:
            for c in competitors:
                parsed = parse_task(c, llm=self._llm, use_llm=self._use_llm)
                primary = parsed.primary_competitor
                if primary and primary != "unknown" and primary not in names:
                    names.append(primary)
        if len(names) < 2:
            raise ValueError("对比需要两个及以上竞品（或用 /compare A 和 B）")
        return self._run_compare(names)

    def _run_compare(self, names: list[str], session_id: str | None = None) -> ComparisonReport:
        """N 向对比执行（设计文档 62 §3.5）：多竞品并行分析（硬上限），按输入顺序稳定返回。

        不再读取 execution.mode（设计文档 62 §3.8：并行与否归 Lead/delegate，代码只守
        execution.max_parallel_subagents 硬上限）；单竞品失败不回滚整体。
        """
        self._emit(
            ProgressEvent(
                event="phase_start",
                phase="compare",
                message=f"N 向对比 {len(names)} 个竞品: {', '.join(names)}",
            )
        )
        workers = min(self._config.execution.max_parallel_subagents, len(names))
        if len(names) <= 1 or workers <= 1:
            reports = [self.analyze(name, session_id=session_id) for name in names]
        else:
            self._emit(
                ProgressEvent(
                    event="phase_start",
                    phase="compare",
                    message=f"并行分析 {len(names)} 个竞品，max_workers={workers}",
                )
            )
            done: list[CompetitorReport] = []
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cmp") as pool:
                futures = {
                    pool.submit(self.analyze, name, session_id=session_id): name
                    for name in names
                }
                for future in as_completed(futures):
                    try:
                        done.append(future.result())
                    except Exception:  # 单竞品失败不影响对比整体
                        logger.exception("并行对比竞品 %s 失败", futures[future])
            by_name = {r.competitor.name: r for r in done}
            reports = [by_name[n] for n in names if n in by_name]
        comparison = self._builder.build_comparison(reports)
        self._export_comparison_json(comparison)
        return comparison

    def _run_discovery(self, task: str, session_id: str | None = None) -> ComparisonReport:
        """市场普查/发现执行（设计文档 62 §3.5）：联网枚举候选 → 逐个分析 → 品类格局报告。

        候选枚举仍由 CompetitorDiscoverer（web_tool）负责；逐竞品分析走 Lead ReAct，
        官方源经 _task_with_sources 注入（避免未知竞品 0 候选 → 0 维度）。
        """
        competitors = self._discoverer.discover(
            task,
            on_candidate=lambda n: self._emit(
                ProgressEvent(
                    event="discovery.candidate",
                    phase="strategic",
                    message=f"发现候选: {n}",
                    payload={"candidate": n},
                )
            ),
        )
        if not competitors:
            raise ValueError(f"未能发现任何竞品: {task[:60]}")
        names = [c.name for c in competitors]
        self._emit(
            ProgressEvent(
                event="discovery",
                phase="strategic",
                message=f"发现 {len(names)} 个候选竞品: {', '.join(names)}",
                payload={"candidates": names},
            )
        )
        reports = [
            self.analyze(self._task_with_sources(c), session_id=session_id)
            for c in competitors
        ]
        return self._builder.build_comparison(reports)

    @staticmethod
    def _task_with_sources(competitor: Competitor) -> str:
        """把发现竞品的 official_links 注入任务文本，使 Lead 拿到官方源。

        复用 parse_task 的 custom_sources 提取（"官网是 …"/"定价页是 …"），
        避免发现出的未知竞品因无官方源而 0 候选 → 0 维度。
        """
        parts = [f"分析 {competitor.name}"]
        label = {"home": "官网是", "pricing": "定价页是", "docs": "文档是", "changelog": "更新日志是"}
        for key, text in label.items():
            url = competitor.official_links.get(key)
            if url:
                parts.append(f"{text} {url}")
        return "，".join(parts)

    def continue_analysis(self, session_id: str) -> CompetitorReport:
        """恢复未完成的会话（对齐 hermes -c/--continue 语义）"""
        return self.resume(session_id)

    def refresh_stale(
        self,
        ttl_override: dict[str, int] | None = None,
        recompute_all: bool = False,
    ) -> list[CompetitorReport]:
        """陈旧度检测 + 定时重爬（设计文档 26 §3.3）。

        扫描记忆/存档中每个竞品的最新会话，按维度 TTL 判定过期后重分析。
        逐竞品分析走 run()/analyze（并行归 Lead delegate）；单竞品失败不回滚整体。

        Args:
            ttl_override: 覆盖默认维度 TTL（天），None 用 config.freshness。
            recompute_all: True 时无视新鲜度，全部竞品重新分析（CLI --all）。
        Returns:
            刷新后的报告列表。
        """
        if self._memory is None:
            return []
        ttl = dict(self._config.freshness.dimension_ttl_days)
        if ttl_override:
            ttl.update(ttl_override)
        if not recompute_all and not self._config.freshness.refresh_check_enabled:
            return []

        # 每个竞品只取最新会话（list_sessions 已按 created_at 降序）
        latest: dict[str, object] = {}
        for s in self._memory.list_sessions():
            comp = getattr(s, "competitor_name", "")
            if not comp or " / " in comp:
                continue  # 跳过对比/发现的聚合会话
            if comp not in latest:
                latest[comp] = s

        refreshed: list[CompetitorReport] = []
        for comp, session in latest.items():
            stale = stale_under_ttl(getattr(session, "raw", None) or {}, ttl) if not recompute_all else []
            if not recompute_all and not stale:
                continue
            report = self.analyze(comp, session_id=f"refresh_{uuid.uuid4().hex[:8]}")
            refreshed.append(report)
            self._emit(
                ProgressEvent(
                    event="refreshed",
                    phase="refresh",
                    message=f"已刷新 {comp}",
                    payload={"competitor": comp, "stale_dimensions": stale or None},
                )
            )
        return refreshed

    def _emit(self, event: ProgressEvent) -> None:
        if self._event_sink is not None:
            self._event_sink(event)
