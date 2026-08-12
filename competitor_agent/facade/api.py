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

import logging
import threading
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.agent.react_loop import ReactLoop
from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.analyzers.registry import AnalyzerRegistry
from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.collector.web_extractor import WebExtractor
from competitor_agent.config.loader import AppConfig, load_config
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
from competitor_agent.core.input_sanitizer import sanitize_task
from competitor_agent.core.report_builder import ReportBuilder
from competitor_agent.core.stop_verifier import StopVerifier
from competitor_agent.core.strategic_loop import StrategicPlanner
from competitor_agent.core.tactical_loop import TacticalLoop
from competitor_agent.core.task_parser import parse_task
from competitor_agent.domain_types.enums import TerminalState
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.domain_types.info_gap import InfoGap
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
    ) -> None:
        # 配置注入：显式参数优先，其次 config，最后默认值
        cfg = config or load_config()
        max_iterations = max_iterations if max_iterations is not None else cfg.budget.max_iterations
        cost_limit = cost_limit if cost_limit is not None else cfg.budget.cost_limit_usd
        self._config = cfg
        self._llm = llm
        self._use_llm = use_llm
        self._event_sink = event_sink
        self._memory = memory

        self._planner = StrategicPlanner(llm=llm, use_llm=use_llm)
        self._selector = SourceSelector()
        if memory is not None:
            self._selector.set_success_rates(memory.source_success_rates())
        self._extractor = extractor or WebExtractor()
        self._analyzers = AnalyzerRegistry(llm=llm, use_llm=use_llm)
        self._builder = ReportBuilder()
        self._budget = BudgetController(max_iterations=max_iterations, cost_limit=cost_limit)
        self._verifier = StopVerifier()

        # RAG 知识库：采集后摄入 + 分析前检索注入（外部事实依据，降低幻觉）
        from competitor_agent.knowledge_base.competitor_store import CompetitorStore
        from competitor_agent.knowledge_base.ingester import Ingester
        from competitor_agent.knowledge_base.retriever import Retriever

        self._store = CompetitorStore()
        self._ingester = Ingester(store=self._store)
        self._retriever = Retriever(store=self._store)

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
        if mode == "team":
            return self.analyze_team(task, session_id=sid)
        self._emit(ProgressEvent(event="phase_start", phase="strategic", message=f"规划: {task}"))

        strategy = self._planner.plan(task, memory=self._memory)
        self._emit(
            ProgressEvent(
                event="phase_complete",
                phase="strategic",
                message=f"识别竞品 {strategy.competitor.name}，{len(strategy.gaps)} 个缺口",
            )
        )

        results: list[DimensionResult] = []
        iteration_budget = IterationBudget(
            max_iterations=self._budget.max_iterations,
            cost_limit=self._budget.cost_limit,
        )

        results = self._run_gaps(strategy, iteration_budget, sid, task)

        stop = self._budget.should_stop(strategy.gaps)
        pending = [g for g in strategy.gaps if not g.is_closed]
        terminal = self._terminal_state(stop.reason, strategy)

        report = self._builder.build(
            competitor=strategy.competitor,
            results=results,
            gaps_pending=pending,
            terminal_state=terminal.value,
        )
        if is_cancelled(sid):
            # 取消完成：保留 checkpoint 供 /resume 续跑，返回带部分结果的取消报告
            logger.info("会话 %s 取消后返回部分结果（%d 个维度）", sid, len(results))
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
        # 分析正常完成：清理 checkpoint
        delete_checkpoint(sid)
        self._emit(
            ProgressEvent(
                event="report",
                phase="report",
                progress=1.0,
                message=f"报告生成完成，终态={terminal.value}",
            )
        )
        return report

    # ── 单 Agent 路径：缺口执行调度（串行 / 并行）───────────────────

    def _run_gaps(
        self,
        strategy: CompetitorStrategy,
        iteration_budget: IterationBudget,
        sid: str,
        task: str,
    ) -> list[DimensionResult]:
        """执行全部独立缺口：execution.mode == parallel 时并行，否则串行（与历史行为一致）。"""
        if self._config.execution.mode != "parallel" or len(strategy.gaps) < 2:
            return self._run_gaps_serial(strategy, iteration_budget, sid, task)
        return self._run_gaps_parallel(strategy, iteration_budget, sid, task)

    def _run_gaps_serial(
        self,
        strategy: CompetitorStrategy,
        iteration_budget: IterationBudget,
        sid: str,
        task: str,
    ) -> list[DimensionResult]:
        results: list[DimensionResult] = []
        completed_lock = threading.Lock()
        for gap in strategy.gaps:
            self._run_gap(strategy, gap, iteration_budget, results, completed_lock, sid, task)
        return results

    def _run_gaps_parallel(
        self,
        strategy: CompetitorStrategy,
        iteration_budget: IterationBudget,
        sid: str,
        task: str,
    ) -> list[DimensionResult]:
        gaps = list(strategy.gaps)
        workers = min(self._config.execution.max_parallel_subagents, len(gaps))
        self._emit(
            ProgressEvent(
                event="phase_start",
                phase="execution",
                message=f"并行执行 {len(gaps)} 个缺口，max_workers={workers}",
            )
        )
        completed: list[DimensionResult] = []
        completed_lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gap") as pool:
            futures = {
                pool.submit(
                    self._run_gap, strategy, gap, iteration_budget, completed, completed_lock, sid, task
                ): gap
                for gap in gaps
            }
            for future in as_completed(futures):
                gap = futures[future]
                try:
                    future.result()
                except Exception:  # 单缺口异常不影响整体
                    logger.exception("并行缺口 %s 执行失败", gap.field)

        # 按缺口原始顺序稳定返回（与串行路径一致）
        by_field = {r.dimension: r for r in completed}
        return [by_field[g.field] for g in gaps if g.field in by_field]

    def _run_gap(
        self,
        strategy: CompetitorStrategy,
        gap: InfoGap,
        iteration_budget: IterationBudget,
        completed: list[DimensionResult],
        completed_lock: threading.Lock,
        sid: str,
        task: str,
    ) -> DimensionResult | None:
        """执行单个缺口闭环：预算/取消检查 → TacticalLoop → 结果合并 + 记忆/预算/checkpoint。

        串行与并行共用此实现；并行下多个缺口共享同一迭代预算与取消标志。
        """
        if self._budget.should_stop(strategy.gaps).should_stop:
            return None
        if is_cancelled(sid):
            logger.info("会话 %s 被取消，停止分析", sid)
            return None
        self._emit(
            ProgressEvent(
                event="phase_start",
                phase=f"tactical.{gap.field}",
                progress=0.3,
                message=f"采集并分析 {gap.field}",
            )
        )
        analyzer = self._analyzers.get(gap.field)
        loop = TacticalLoop(
            selector=self._selector,
            extractor=self._extractor,
            analyzer=analyzer,
            budget=iteration_budget,
            ingester=self._ingester,
            retriever=self._retriever,
            session_id=sid,
        )
        result = loop.execute(gap, strategy)
        # 每完成一个缺口保存 checkpoint（结果快照 + 共享预算用量）
        with completed_lock:
            if result is not None:
                completed.append(result)
            completion = list(completed)
        if result is not None:
            self._record_memory_success(strategy, gap)
        self._budget.record_iteration(cost=0.01)
        save_checkpoint(
            session_id=sid,
            task=task,
            competitor_name=strategy.competitor.name,
            gaps=strategy.gaps,
            dimension_results=completion,
            iterations_used=iteration_budget.used_iterations,
            max_iterations=self._budget.max_iterations,
            cost_used=iteration_budget.used_cost,
            cost_limit=self._budget.cost_limit,
            sources_tried=[s for g in strategy.gaps for s in g.sources_tried],
        )
        return result

    @property
    def memory(self) -> IFourLayerMemory | None:
        return self._memory

    def analyze_react(self, task: str) -> str:
        """ReAct 模式：LLM 驱动工具调用（需 LLM Key）

        web_extract 工具接入真实采集链路（复用 self._extractor），非占位实现。
        """
        dispatcher = ToolDispatcher()
        dispatcher.register("web_extract", self._react_web_extract)
        agent = ReactAgent(llm=self._llm or LLMClient(), dispatcher=dispatcher)
        loop = ReactLoop(agent, event_sink=self._event_sink)
        return loop.run(task)

    def _react_web_extract(self, url: str) -> str:
        """ReAct 工具：真实抓取给定 URL 的页面文本（失败返回可读信息）。"""
        try:
            obs = self._extractor.fetch(
                InfoGap(field="web"),
                SourceContext(competitor_name="", query="web", kwargs={"url": url}),
            )
        except DataSourceUnavailableError as exc:
            return f"抓取失败: {exc}"
        return (obs.raw_text or "").strip()[:2000] or "（页面无文本内容）"

    def analyze_team(
        self,
        task: str,
        session_id: str | None = None,
        max_retries: int = 1,
    ) -> CompetitorReport:
        """多 Agent 流水线模式：Collector→Analyzer→Validator→Reporter 协作产出草稿报告

        事件驱动 + 状态决策：各 Agent 基于 AgentResult 状态（SUCCESS/RETRY/DEGRADED/FAILED）
        决定继续、重试或降级。
        """
        self._emit(ProgressEvent(event="phase_start", phase="strategic", message=f"规划: {task}"))
        orch = TeamOrchestrator(
            extractor=self._extractor,
            llm=self._llm,
            use_llm=self._use_llm,
            memory=self._memory,
            max_retries=max_retries,
            ingester=self._ingester,
            retriever=self._retriever,
            session_id=session_id,
        )
        report = orch.run(task)
        # 记忆闭环：分析成功后沉淀技能 + 记录数据源成功率（与单 Agent 路径对齐）
        self._record_team_memory_success(report)
        self._emit(
            ProgressEvent(
                event="report",
                phase="team_orchestrator",
                progress=1.0,
                message=f"多 Agent 报告生成完成，{len(report.dimension_results)} 个维度",
            )
        )
        if session_id and is_cancelled(session_id):
            logger.info("会话 %s 取消后返回部分结果（%d 个维度）", session_id, len(report.dimension_results))
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

    # ── M4: 流式分析 ──────────────────────────────────────────────────

    async def analyze_stream(self, task: str, session_id: str | None = None) -> AsyncIterator[ProgressEvent]:
        """流式分析：逐条 yield ProgressEvent（供 Web SSE 消费）"""
        sid = session_id or f"sess_{uuid.uuid4().hex[:8]}"

        def _sink(event: ProgressEvent) -> None:
            self._emit(event)

        api = CompetitorAnalysisAPI(
            llm=self._llm,
            use_llm=self._use_llm,
            max_iterations=self._budget.max_iterations,
            cost_limit=self._budget.cost_limit,
            event_sink=_sink,
            extractor=self._extractor,
            memory=self._memory,
            config=self._config,
        )

        yield ProgressEvent(
            event="session_started",
            phase="init",
            message=f"会话 {sid} 已启动",
            payload={"session_id": sid},
        )

        import asyncio

        loop = asyncio.get_running_loop()
        report = await loop.run_in_executor(None, api.analyze, task, None, "team", sid)

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

        # 归档会话
        if self._memory is not None:
            self._memory.archive_session(
                AnalysisSession(
                    task=task,
                    competitor_name=report.competitor.name,
                    session_id=sid,
                    raw={
                        "terminal_state": report.terminal_state,
                        "dimension_count": len(report.dimension_results),
                    },
                )
            )

    # ── M4: 中断与断点续跑 ───────────────────────────────────────────

    def cancel(self, session_id: str) -> None:
        """请求取消运行中的分析会话"""
        set_cancel(session_id)
        logger.info("已请求取消会话: %s", session_id)

    def resume(self, session_id: str) -> CompetitorReport:
        """从 checkpoint 恢复未完成的分析会话"""
        cp = load_checkpoint(session_id)
        if cp is None:
            raise ValueError(f"会话 {session_id} 无 checkpoint，无法恢复")
        logger.info("从 checkpoint 恢复会话: %s (%d gaps)", session_id, len(cp.gaps))
        report = checkpoint_to_report(cp)
        delete_checkpoint(session_id)
        return report

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

        if competitor:
            sessions = self._memory._sessions.retrieve(competitor)  # type: ignore[attr-defined]
        else:
            sessions = self._memory.recent_sessions()  # type: ignore[attr-defined]

        reports: list[CompetitorReport] = []
        for s in sessions:
            raw = s.raw if hasattr(s, "raw") else {}
            from competitor_agent.domain_types.competitor import Competitor

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

    def compare(self, a: str, b: str | None = None) -> ComparisonReport:
        """竞品对比：两个竞品（或一个"对比 A 和 B"任务）→ 对比报告

        内部复用 parse_task 的对比拆分；逐个 analyze 后拼装 ComparisonReport。
        """
        if b is None:
            parsed = parse_task(a, llm=self._llm, use_llm=self._use_llm)
            if len(parsed.competitors) >= 2:
                a_name, b_name = parsed.competitors[0], parsed.competitors[1]
            else:
                a_name = parsed.primary_competitor
                b_name = ""
        else:
            a_name = parse_task(a, llm=self._llm, use_llm=self._use_llm).primary_competitor
            b_name = parse_task(b, llm=self._llm, use_llm=self._use_llm).primary_competitor

        if not b_name:
            raise ValueError("对比需要两个竞品（或用 /compare A 和 B）")

        report_a = self.analyze(a_name)
        report_b = self.analyze(b_name)
        markdown = self._build_comparison_markdown(report_a, report_b)
        return ComparisonReport(
            competitors=[report_a.competitor, report_b.competitor],
            reports=[report_a, report_b],
            markdown_report=markdown,
        )

    def _build_comparison_markdown(
        self,
        a: CompetitorReport,
        b: CompetitorReport,
    ) -> str:
        """拼装对比 Markdown（维度 × 竞品表格 + 摘要）"""
        name_a = a.competitor.name
        name_b = b.competitor.name
        lines = [f"# {name_a} vs {name_b} 对比报告", ""]
        lines.append("| 维度 | 置信度 A | 置信度 B |")
        lines.append("|------|:--------:|:--------:|")
        dims_a = {r.dimension: r for r in a.dimension_results}
        dims_b = {r.dimension: r for r in b.dimension_results}
        all_dims = list(dict.fromkeys([*dims_a.keys(), *dims_b.keys()]))
        for dim in all_dims:
            conf_a = f"{dims_a[dim].confidence:.2f}" if dim in dims_a else "-"
            conf_b = f"{dims_b[dim].confidence:.2f}" if dim in dims_b else "-"
            lines.append(f"| {dim} | {conf_a} | {conf_b} |")
        lines.append("")
        lines.append(f"总置信度：{a.overall_confidence:.2f} vs {b.overall_confidence:.2f}")
        return "\n".join(lines)

    def continue_analysis(self, session_id: str) -> CompetitorReport:
        """恢复未完成的会话（对齐 hermes -c/--continue 语义）"""
        return self.resume(session_id)

    def _terminal_state(self, reason: str, strategy: CompetitorStrategy) -> TerminalState:
        if reason in (StopReason.ALL_GAPS_CLOSED, StopReason.CORE_SATISFACTION_REACHED, StopReason.NO_GAPS):
            return TerminalState.SUCCESS
        if reason in (StopReason.ITERATION_BUDGET_EXHAUSTED, StopReason.COST_LIMIT_REACHED):
            return TerminalState.PARTIAL
        return TerminalState.DEGRADED

    def _emit(self, event: ProgressEvent) -> None:
        if self._event_sink is not None:
            self._event_sink(event)

    def _record_memory_success(self, strategy: CompetitorStrategy, gap: object) -> None:
        """分析成功后沉淀技能 + 记录数据源成功率（记忆自动进化）"""
        if self._memory is None:
            return
        gap_field = getattr(gap, "field", "")
        competitor = strategy.competitor.name
        # 技能沉淀：取最后一个成功尝试的源
        tried = getattr(gap, "sources_tried", None)
        source = tried[-1] if tried else ""
        if source:
            self._memory.record_skill(
                Skill(competitor_name=competitor, gap_field=gap_field, source_name=source, success=True)
            )
            self._memory.record_outcome(source, True)
