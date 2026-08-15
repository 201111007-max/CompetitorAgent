"""CompetitorAnalysisAPI — 外部唯一入口

组装：StrategicLoop（规划）→ 逐缺口 TacticalLoop（采集+分析）
     → BudgetController（终止）→ ReportBuilder（汇总）
M1 默认 LLM 关闭（use_llm=False），无 Key 也能产出报告（规则降级）。
M6 默认 LLM 开启（use_llm=True），主路径用 LLM 理解用户输入；无 Key 时自动降级规则。

M4 新增：
- analyze_stream(): 流式分析（SSE 事件推送）
- cancel() / resume(): 中断与断点续跑
- get_history(): 历史查询
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.agent.react_loop import ReactLoop, ReactRunResult
from competitor_agent.agent.tool_registry import build_react_dispatcher
from competitor_agent.analyzers.registry import AnalyzerRegistry
from competitor_agent.collector.providers import build_providers
from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.collector.web_extractor import WebExtractor
from competitor_agent.config.loader import AppConfig, load_config
from competitor_agent.core.alerting import Alert, AlertSink, ConsoleAlertSink
from competitor_agent.core.alerting import report_diff as _diff_to_alerts
from competitor_agent.core.budget import IterationBudget
from competitor_agent.core.budget_controller import BudgetController, StopReason
from competitor_agent.core.checkpoint import (
    checkpoint_to_report,
    delete_checkpoint,
    is_cancelled,
    load_checkpoint,
    save_checkpoint,
    set_cancel,
)
from competitor_agent.core.competitor_discoverer import CompetitorDiscoverer
from competitor_agent.core.input_sanitizer import sanitize_task
from competitor_agent.core.orchestrator import SingleOrchestrator
from competitor_agent.core.report_builder import ReportBuilder
from competitor_agent.core.report_exporter import (
    export_comparison_json,
    export_competitor_json,
)
from competitor_agent.core.stop_verifier import StopVerifier
from competitor_agent.core.strategic_loop import StrategicPlanner
from competitor_agent.core.task_parser import parse_task
from competitor_agent.core.url_guard import URLError, guard_http_url
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import GapStatus, ResultStatus, TerminalState
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.domain_types.freshness import stale_under_ttl
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import SourceEvidence
from competitor_agent.domain_types.report import (
    CancelledResult,
    ComparisonReport,
    CompetitorReport,
    DimensionResult,
)
from competitor_agent.domain_types.strategy import CompetitorStrategy
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
from competitor_agent.team.orchestrator import TeamOrchestrator

logger = logging.getLogger("competitor_agent.facade.api")


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
    ) -> None:
        # 配置注入：显式参数优先，其次 config，最后默认值
        cfg = config or load_config()
        max_iterations = max_iterations if max_iterations is not None else cfg.budget.max_iterations
        cost_limit = cost_limit if cost_limit is not None else cfg.budget.cost_limit_usd
        self._config = cfg
        self._llm = llm
        self._use_llm = use_llm
        self._event_sink = event_sink
        # enable_memory=False：门控全部记忆副作用（set_success_rates / _apply_memory_boost /
        # record_skill / record_outcome / archive_session），下游均判 `self._memory is None`
        self._memory = memory if enable_memory else None

        self._planner = StrategicPlanner(llm=llm, use_llm=use_llm)
        # 外部源提供方（设计文档 23）：按 config 构造；主开关默认关闭（无网络/无 Key 不触发真实网络）
        providers = build_providers(cfg.collector)
        self._providers: dict[str, object] = {p.kind: p for p in providers}
        self._selector = SourceSelector(providers=providers)
        if self._memory is not None:
            self._selector.set_success_rates(self._memory.source_success_rates())
        self._extractor = extractor or WebExtractor()
        self._analyzers = AnalyzerRegistry(llm=llm, use_llm=use_llm)
        # 新鲜度 TTL（设计文档 26）：build() 为报告计算 freshness 元数据
        self._builder = ReportBuilder(dimension_ttl_days=cfg.freshness.dimension_ttl_days)
        self._budget = BudgetController(max_iterations=max_iterations, cost_limit=cost_limit)
        self._verifier = StopVerifier()
        # 竞品时间线记忆（设计文档 26 §3.4）：跨分析 diff，独立于四层记忆
        self._timeline = timeline or TimelineMemory()

        # RAG 知识库：采集后摄入 + 分析前检索注入（外部事实依据，降低幻觉）
        # enable_rag=False：不组装知识库，GapExecutor/分析器对 None 走"跳过摄入/跳过检索"路径
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
        else:
            self._store = None
            self._ingester = None
            self._retriever = None
            self._vector_store = None
            self._store = None
            self._ingester = None
            self._retriever = None

        # 竞品发现器（设计文档 20）：仅 DISCOVERY 意图时被调用，web_tool 可注入
        self._discoverer = CompetitorDiscoverer(llm=llm, use_llm=use_llm, web_tool=web_tool)

    def analyze(
        self,
        task: str,
        conversation_history: list[ChatMessage] | None = None,
        mode: str = "team",
        session_id: str | None = None,
    ) -> CompetitorReport:
        """单竞品分析：输入任务文本 → CompetitorReport

        Args:
            task: 用户任务文本（入站先做浅清洗 sanitize_task）
            conversation_history: 上一轮对话历史（ChatMessage 列表），
                传入则把前序上下文摘要并入任务解析，支持多轮追问。
            mode: 执行模式，team=多 Agent 流水线（默认），single=单 Agent 串行。
            session_id: 外部会话 ID（如 Web 端 sid）。传入时复用，使内部取消标志
                与外部一致（解决 Web 取消断链）；留空则自动生成。
        """
        task = sanitize_task(task)
        task = self._disambiguate_with_history(task, conversation_history)
        sid = session_id or f"sess_{uuid.uuid4().hex[:8]}"
        set_current_session(sid)
        if mode == "team":
            # team 路径自含 session_started 与规划埋点（analyze_team 内部统一）
            return self.analyze_team(task, session_id=sid)
        slog = get_session_logger(sid)
        log_event(slog, "session_started", "init", f"会话 {sid} 启动", task=task)
        self._emit(ProgressEvent(event="phase_start", phase="strategic", message=f"规划: {task}"))

        strategy = self._planner.plan(task, memory=self._memory)
        self._emit(
            ProgressEvent(
                event="phase_complete",
                phase="strategic",
                message=f"识别竞品 {strategy.competitor.name}，{len(strategy.gaps)} 个缺口",
            )
        )
        log_event(
            slog, "competitor.resolved", "strategic",
            f"识别竞品 {strategy.competitor.name}",
            competitor=strategy.competitor.name,
            source="registry" if strategy.competitor.official_links else "unknown",
        )
        log_event(
            slog, "gaps.planned", "strategic",
            f"规划 {len(strategy.gaps)} 个缺口",
            gap_fields=[g.field for g in strategy.gaps],
        )

        results: list[DimensionResult] = []
        iteration_budget = IterationBudget(
            max_iterations=self._budget.max_iterations,
            cost_limit=self._budget.cost_limit,
        )

        results = self._orchestrator_for("single").run(
            strategy, iteration_budget, sid, task,
            event_sink=self._emit, memory=self._memory,
        )

        stop = self._budget.should_stop(strategy.gaps)
        pending = [g for g in strategy.gaps if not g.is_closed]
        terminal = self._terminal_state(stop.reason, strategy)
        log_event(
            slog, "analysis.terminated", "terminate",
            f"分析终止，终态={terminal.value}，原因={stop.reason}",
            terminal_state=terminal.value, reason=stop.reason,
        )

        report = self._builder.build(
            competitor=strategy.competitor,
            results=results,
            gaps_pending=pending,
            terminal_state=terminal.value,
        )
        log_event(
            slog, "report.built", "report",
            f"报告生成，{len(report.dimension_results)} 个维度",
            dimension_count=len(report.dimension_results),
            overall_confidence=round(report.overall_confidence, 3),
        )
        if is_cancelled(sid):
            # 取消完成：保留 checkpoint 供 /resume 续跑，返回带部分结果的取消报告
            logger.info("会话 %s 取消后返回部分结果（%d 个维度）", sid, len(results))
            close_session_log(sid)
            self._emit(
                ProgressEvent(
                    event="cancelled",
                    phase="report",
                    message=f"分析已取消，返回 {len(results)} 个已完成维度",
                )
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
                message=f"报告生成完成，终态={terminal.value}",
            )
        )
        return report

    # ── 统一编排：single 委托 SingleOrchestrator（问题 20 收敛缺口执行闭环）──

    def _orchestrator_for(self, mode: str) -> SingleOrchestrator:
        """按 mode 返回编排器：single 用缺口级闭环（复用 GapExecutor 采集分析段）。"""
        return SingleOrchestrator(
            config=self._config,
            budget=self._budget,
            selector=self._selector,
            extractor=self._extractor,
            analyzers=self._analyzers,
            ingester=self._ingester,
            retriever=self._retriever,
            memory=self._memory,
            providers=self._providers,
        )

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
            r.details.get("pricing")
            for r in report.dimension_results
            if isinstance(r.details, dict) and isinstance(r.details.get("pricing"), dict)
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
        """设计文档 28：config.report.export_json 开启时导出 reports/competitor/<竞品>.json。

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
            pass
        return path

    def _export_comparison_json(self, report: ComparisonReport) -> Path | None:
        """设计文档 28：比较报告导出 reports/comparison/<names>.json（品类矩阵）。"""
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
            pass
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
            report = self.analyze(name, mode="team", session_id=f"schedule_{uuid.uuid4().hex[:8]}")
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
        """ReAct 模式：LLM 驱动工具调用（需 LLM Key），返回结论文本。

        MCP 工具集多工具自主调用（设计文档 40）：web_search/github/pricing 等统一经
        build_react_dispatcher 注册；web_extract 复用真实采集链路 + URL 守卫（设计文档 41）。
        与主路径共享统一会话上下文（设计文档 43 §2.2）：session_id 取消协作、
        IterationBudget 步数预算、记忆/RAG 注入、事件推送，步数计入共享 BudgetController。
        """
        loop = self._react_loop(task, session_id)
        result = loop.run_with_result(task)
        if result.steps:
            self._budget.record_iteration(cost=0.01 * result.steps)
        return result.answer

    def analyze_react_report(self, task: str, session_id: str | None = None) -> CompetitorReport:
        """ReAct 模式结构化入口（设计文档 43 §2.3）：产物入 CompetitorReport 而非裸字符串。

        共享与 analyze 同源的会话上下文；结论文本优先按结构化 JSON
        （summary/details/confidence，对齐设计文档 34 schema）解析为 DimensionResult，
        非 JSON 时降级为单个 react 维度（summary=结论文本）。取消/预算耗尽 → 终态标注。
        """
        loop = self._react_loop(task, session_id)
        result = loop.run_with_result(task)
        if result.steps:
            self._budget.record_iteration(cost=0.01 * result.steps)
        terminal = (
            "cancelled"
            if result.cancelled
            else ("partial" if result.budget_exhausted else "success")
        )
        dr = self._react_dimension_result(result)
        report = self._builder.build(
            competitor=self._react_competitor(task),
            results=[dr] if dr is not None else [],
            gaps_pending=[],
            terminal_state=terminal,
        )
        return report

    def _react_loop(self, task: str, session_id: str | None) -> ReactLoop:
        """组装共享会话上下文的 ReactLoop（取消/预算/记忆/RAG/事件，与 analyze 同源）。"""
        dispatcher = build_react_dispatcher(
            config=self._config,
            web_extract=self._react_web_extract,
        )
        agent = ReactAgent(llm=self._llm or LLMClient(), dispatcher=dispatcher)
        budget = IterationBudget(
            max_iterations=self._budget.max_iterations,
            cost_limit=self._budget.cost_limit,
        )
        return ReactLoop(
            agent,
            event_sink=self._event_sink,
            session_id=session_id,
            budget=budget,
            memory_context_fn=self._react_memory_context,
            rag_fn=self._react_rag_context,
        )

    def _react_competitor(self, task: str) -> Competitor:
        """从任务解析竞品（注册表命中带官方源；未知竞品退化为裸名）。"""
        from competitor_agent.core.competitor_registry import resolve_competitor

        try:
            name = parse_task(task, llm=self._llm, use_llm=self._use_llm).primary_competitor
        except Exception:  # noqa: BLE001 — 解析失败不影响 ReAct 产物
            name = ""
        if name and name != "unknown":
            competitor = resolve_competitor(name)
            if competitor is not None:
                return competitor
        return Competitor(name=name or "unknown")

    def _react_memory_context(self, task: str) -> str:
        """记忆召回（设计文档 35 recent_context，与 single 路径同口径）：失败静默降级。"""
        if self._memory is None:
            return ""
        comp = self._react_competitor(task).name
        if not comp or comp == "unknown":
            return ""
        try:
            return "\n".join(self._memory.recent_context(comp, top_k=3, query=task))
        except Exception:  # noqa: BLE001 — 记忆召回失败不影响推理
            logger.warning("ReAct 记忆召回失败: %s", comp, exc_info=True)
            return ""

    def _react_rag_context(self, task: str) -> str:
        """RAG 检索（与 GapExecutor._retrieve_rag 同口径）：失败静默降级。"""
        if self._retriever is None:
            return ""
        comp = self._react_competitor(task).name
        try:
            chunks = self._retriever.retrieve(
                query=task, competitor=comp, dimension="", top_k=5
            )
        except Exception:  # noqa: BLE001 — 检索失败不影响推理
            logger.warning("ReAct RAG 检索失败: %s", comp, exc_info=True)
            return ""
        if not chunks:
            return ""
        lines = []
        for c in chunks:
            src = f"（来源: {c.source_url}）" if c.source_url else ""
            lines.append(f"- [{c.competitor}/{c.dimension}]{src} {c.text[:300]}")
        return "\n".join(lines)

    def _react_dimension_result(self, result: ReactRunResult) -> DimensionResult | None:
        """把 ReAct 结论文本归一化为 DimensionResult（结构化 JSON 优先，降级为单 react 维度）。

        LLM 不可用等降级文案 → PARTIAL 低置信（不把"服务不可用"标成 COMPLETE）。
        """
        answer = (result.answer or "").strip()
        parsed = None
        if answer.startswith("{"):
            try:
                parsed = json.loads(answer)
            except json.JSONDecodeError:
                parsed = None
        if isinstance(parsed, dict) and "summary" in parsed:
            confidence = float(parsed.get("confidence", 0.7))
            return DimensionResult(
                dimension="react",
                summary=str(parsed.get("summary", "")),
                details=parsed.get("details", {}) if isinstance(parsed.get("details"), dict) else {},
                confidence=confidence,
                status=ResultStatus.COMPLETE if confidence >= 0.5 else ResultStatus.PARTIAL,
            )
        if not answer:
            return None
        if "LLM 服务不可用" in answer:
            return DimensionResult(
                dimension="react",
                summary=answer,
                details={},
                confidence=0.0,
                status=ResultStatus.PARTIAL,
            )
        return DimensionResult(
            dimension="react",
            summary=answer,
            details={},
            confidence=0.7,
            status=ResultStatus.COMPLETE,
        )

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

    def analyze_team(
        self,
        task: str,
        session_id: str | None = None,
        max_retries: int = 1,
    ) -> CompetitorReport:
        """多 Agent 流水线：Collector→Analyzer→Validator→Reporter 协作产出草稿报告

        事件驱动 + 状态决策：各 Agent 基于 AgentResult 状态决定继续、重试或降级。
        与 single 对齐的统一语义（设计文档 18 §2）：同一规划埋点、同一 BudgetController、
        同一 checkpoint 落盘/清理、取消后保留 checkpoint 供 resume。
        """
        strategy, orch, slog = self._begin_team(task, session_id, max_retries)

        # 预算一致性：与 single 共用 BudgetController，耗尽即提前终止
        stop = self._budget.should_stop(strategy.gaps)
        if stop.should_stop:
            logger.info("预算已耗尽（%s），team 提前终止", stop.reason)
            report = self._builder.build(
                competitor=strategy.competitor,
                results=[],
                gaps_pending=list(strategy.gaps),
                terminal_state=self._terminal_state(stop.reason, strategy).value,
            )
        else:
            report = orch.run(task, strategy=strategy)
            self._budget.record_iteration(cost=0.01)

        return self._finish_team(report, task, session_id, strategy, slog)

    async def analyze_team_async(
        self,
        task: str,
        session_id: str | None = None,
        max_retries: int = 1,
        max_parallel: int = 4,
    ) -> CompetitorReport:
        """异步多 Agent 流水线（设计文档 33）：与 analyze_team 语义一致，
        但编排走 TeamOrchestrator.run_async——Collector 总线驱动、Analyzer 按缺口并行、
        Validator 冲突仲裁。默认入口仍为同步 run()（回归安全网），本方法为可选 async 入口。
        """
        strategy, orch, slog = self._begin_team(task, session_id, max_retries, max_parallel)

        # 预算一致性：与 single 共用 BudgetController，耗尽即提前终止
        stop = self._budget.should_stop(strategy.gaps)
        if stop.should_stop:
            logger.info("预算已耗尽（%s），team 提前终止", stop.reason)
            report = self._builder.build(
                competitor=strategy.competitor,
                results=[],
                gaps_pending=list(strategy.gaps),
                terminal_state=self._terminal_state(stop.reason, strategy).value,
            )
        else:
            report = await orch.run_async(task, strategy=strategy)
            self._budget.record_iteration(cost=0.01)

        return self._finish_team(report, task, session_id, strategy, slog)

    def _begin_team(
        self,
        task: str,
        session_id: str | None,
        max_retries: int,
        max_parallel: int = 4,
    ) -> tuple[CompetitorStrategy, TeamOrchestrator, object]:
        """analyze_team / analyze_team_async 共用前置：会话埋点 + 统一规划 + 组装编排器。"""
        self._emit(ProgressEvent(event="phase_start", phase="strategic", message=f"规划: {task}"))
        set_current_session(session_id)
        slog = get_session_logger(session_id)
        log_event(slog, "session_started", "init", f"会话 {session_id} 启动（team 模式）", task=task)

        # 统一规划（与 single 一致：competitor.resolved / gaps.planned 埋点）
        strategy = self._planner.plan(task, memory=self._memory)
        log_event(
            slog, "competitor.resolved", "strategic",
            f"识别竞品 {strategy.competitor.name}",
            competitor=strategy.competitor.name,
            source="registry" if strategy.competitor.official_links else "unknown",
        )
        log_event(
            slog, "gaps.planned", "strategic",
            f"规划 {len(strategy.gaps)} 个缺口",
            gap_fields=[g.field for g in strategy.gaps],
        )

        orch = TeamOrchestrator(
            extractor=self._extractor,
            llm=self._llm,
            use_llm=self._use_llm,
            memory=self._memory,
            max_retries=max_retries,
            max_parallel=max_parallel,
            ingester=self._ingester,
            retriever=self._retriever,
            session_id=session_id,
            providers=self._providers,
            builder=self._builder,
        )
        return strategy, orch, slog

    def _finish_team(
        self,
        report: CompetitorReport,
        task: str,
        session_id: str | None,
        strategy: CompetitorStrategy,
        slog: object,
    ) -> CompetitorReport:
        """analyze_team / analyze_team_async 共用收尾：记忆沉淀 + checkpoint + 埋点 + 取消/归档。"""
        # 记忆闭环：分析成功后沉淀技能 + 记录数据源成功率（与单 Agent 路径对齐）
        self._record_team_memory_success(report)

        # checkpoint：无论成功/取消均落盘（供 resume 续跑，与 single 对齐）
        if session_id:
            save_checkpoint(
                session_id=session_id,
                task=task,
                competitor_name=strategy.competitor.name,
                gaps=strategy.gaps,
                dimension_results=report.dimension_results,
                iterations_used=self._budget.iteration_count,
                max_iterations=self._budget.max_iterations,
                cost_used=self._budget.total_cost,
                cost_limit=self._budget.cost_limit,
                sources_tried=[s for g in strategy.gaps for s in g.sources_tried],
            )

        log_event(
            slog, "analysis.terminated", "terminate",
            f"多 Agent 分析终止，终态={report.terminal_state}",
            terminal_state=report.terminal_state or "success",
            dimension_count=len(report.dimension_results),
        )
        log_event(
            slog, "report.built", "report",
            f"报告生成，{len(report.dimension_results)} 个维度",
            dimension_count=len(report.dimension_results),
            overall_confidence=round(report.overall_confidence, 3),
        )
        self._emit(
            ProgressEvent(
                event="report",
                phase="team_orchestrator",
                progress=1.0,
                message=f"多 Agent 报告生成完成，{len(report.dimension_results)} 个维度",
            )
        )
        if session_id and is_cancelled(session_id):
            # 取消：保留 checkpoint 供 /resume 续跑（与 single 语义一致）
            logger.info("会话 %s 取消后返回部分结果（%d 个维度）", session_id, len(report.dimension_results))
            close_session_log(session_id)
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
        # 设计文档 26：记录时间线 diff + 归档带新鲜度的会话（多 Agent 路径同样对齐）
        self._record_timeline(report)
        self._archive_report(report, task, session_id or "")
        self._export_competitor_json(report, session_id or "")
        delete_checkpoint(session_id) if session_id else None
        close_session_log(session_id)
        return report

    def _record_team_memory_success(self, report: CompetitorReport) -> None:
        """多 Agent 路径的记忆沉淀：按报告维度结果记录技能与数据源成功率。"""
        if self._memory is None:
            return
        competitor = report.competitor.name
        for r in report.dimension_results:
            if not r.evidence:
                continue
            source = r.evidence[0].source_name
            if source:
                self._memory.record_skill(
                    Skill(competitor_name=competitor, gap_field=r.dimension, source_name=source, success=True)
                )
                self._memory.record_outcome(source, True)
                # 设计文档 35：多 Agent 路径同样沉淀进化经验（成功模式）
                self._memory.note_pattern(
                    competitor,
                    r.dimension,
                    pattern=f"缺口 {r.dimension} 由源 {source} 有效",
                    outcome="success",
                )

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
        """从 checkpoint 恢复：重建缺口状态与剩余预算，真正重跑未关闭缺口。"""
        cp = load_checkpoint(session_id)
        if cp is None:
            raise ValueError(f"会话 {session_id} 无 checkpoint，无法恢复")
        logger.info("从 checkpoint 恢复会话: %s (%d gaps)", session_id, len(cp.gaps))

        # 1. 重建策略与缺口状态
        # 用注册表恢复官方源（official_links），否则候选源为空、重跑缺口产出 0 结果
        from competitor_agent.core.competitor_registry import resolve_competitor

        competitor = (
            resolve_competitor(cp.competitor_name)
            if cp.competitor_name and cp.competitor_name != "unknown"
            else Competitor(name=cp.competitor_name)
        )
        gaps = self._reconstruct_gaps_from_checkpoint(cp.gaps)
        strategy = CompetitorStrategy(competitor=competitor, gaps=gaps)

        # 2. 重建剩余预算（已消耗部分已预置）
        iteration_budget = IterationBudget(
            max_iterations=cp.max_iterations,
            cost_limit=cp.cost_limit,
        )
        iteration_budget._used_iterations = cp.iterations_used
        iteration_budget._used_cost = cp.cost_used

        # 3. 预置已完成维度（不重跑已关闭缺口）
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

        # 4. 仅重跑未关闭缺口
        open_gaps = [g for g in strategy.gaps if not g.is_closed]
        if open_gaps:
            new_results = self._orchestrator_for("single").run(
                strategy, iteration_budget, session_id, cp.task,
                event_sink=self._emit, memory=self._memory,
            )
            # 合并已关闭维度 + 新完成维度
            by_dim = {r.dimension: r for r in completed}
            for r in new_results:
                by_dim[r.dimension] = r
            results = list(by_dim.values())
        else:
            results = completed

        # 5. 删除 checkpoint（一次性消费），返回当前进度
        pending = [g for g in strategy.gaps if not g.is_closed]
        delete_checkpoint(session_id)

        report = self._builder.build(
            competitor=competitor,
            results=results,
            gaps_pending=pending,
            terminal_state="success" if not pending else "partial",
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
        """
        if not conversation_history:
            return task
        parsed = parse_task(task, llm=self._llm, use_llm=self._use_llm)
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

    def compare(self, *competitors: str) -> ComparisonReport:
        """N 向竞品对比（设计文档 20）：接受 ≥2 个竞品（或单个"对比 A 和 B"任务）。

        兼容旧签名 compare(a, b=None)：单个参数会被解析（"对比 A 和 B" / "A vs B"）；
        多个参数逐个作为竞品名处理。逐个 analyze 后聚合为品类格局对比报告。
        """
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

        self._emit(
            ProgressEvent(
                event="phase_start",
                phase="compare",
                message=f"N 向对比 {len(names)} 个竞品: {', '.join(names)}",
            )
        )
        if self._config.execution.mode == "parallel" and len(names) >= 2:
            reports = self._compare_parallel(names)
        else:
            reports = [self.analyze(name, mode="team") for name in names]
        comparison = self._builder.build_comparison(reports)
        self._export_comparison_json(comparison)
        return comparison

    def _compare_parallel(self, names: list[str]) -> list[CompetitorReport]:
        """execution.mode=parallel 时并行分析多个竞品（共享预算），按输入顺序稳定返回。

        单竞品失败不回滚整体：跳过该竞品，仍聚合其余报告。
        """
        workers = min(self._config.execution.max_parallel_subagents, len(names))
        self._emit(
            ProgressEvent(
                event="phase_start",
                phase="compare",
                message=f"并行分析 {len(names)} 个竞品，max_workers={workers}",
            )
        )
        done: list[CompetitorReport] = []
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cmp") as pool:
            futures = {pool.submit(self.analyze, name, None, "team"): name for name in names}
            for future in as_completed(futures):
                try:
                    done.append(future.result())
                except Exception:  # 单竞品失败不影响对比整体
                    logger.exception("并行对比竞品 %s 失败", futures[future])
        by_name = {r.competitor.name: r for r in done}
        return [by_name[n] for n in names if n in by_name]

    def discover(self, task: str) -> ComparisonReport:
        """市场普查/发现（设计文档 20）：LLM 判定 DISCOVERY 后被调用。

        CompetitorDiscoverer 联网枚举候选（名称 + 官网，无 Key 走内置兜底清单），
        逐个 analyze 后合并为品类格局对比报告——根治"所有 X"拼成假竞品导致 0 维度。
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
        reports = [self.analyze(self._task_with_sources(c), mode="team") for c in competitors]
        return self._builder.build_comparison(reports)

    @staticmethod
    def _task_with_sources(competitor: Competitor) -> str:
        """把发现竞品的 official_links 注入任务文本，使规划/采集拿到官方源。

        复用 parse_task 的 custom_sources 提取（"官网是 …"/"定价页是 …"），
        避免发现出的未知竞品因无 official_links 而 0 候选 → 0 维度。
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
        并发安全沿用 execution.mode（analyze 内部分派）；单竞品失败不回滚整体。

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
            report = self.analyze(comp, mode="team", session_id=f"refresh_{uuid.uuid4().hex[:8]}")
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

    def _terminal_state(self, reason: str, strategy: CompetitorStrategy) -> TerminalState:
        if reason in (StopReason.ALL_GAPS_CLOSED, StopReason.CORE_SATISFACTION_REACHED, StopReason.NO_GAPS):
            return TerminalState.SUCCESS
        if reason in (StopReason.ITERATION_BUDGET_EXHAUSTED, StopReason.COST_LIMIT_REACHED):
            return TerminalState.PARTIAL
        return TerminalState.DEGRADED

    def _emit(self, event: ProgressEvent) -> None:
        if self._event_sink is not None:
            self._event_sink(event)


