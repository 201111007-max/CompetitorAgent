"""TeamOrchestrator — 多 Agent 流水线编排

一条任务：CollectorAgent → AnalyzerAgent → ValidatorAgent → ReporterAgent，
结构化 Artifact 经 MessageBus 传递，最终产出草稿报告。

编排基于 AgentResult 状态做决策：
- SUCCESS：正常进入下一环节
- DEGRADED：降级继续（记录原因）
- RETRY：按策略重试（有限次数）
- FAILED：终止流水线，返回失败

真异步协作（设计文档 33）：run_async 基于 asyncio + MessageBus 异步分发，
Collector 经总线请求/响应，Analyzer 按缺口并行（Semaphore 限流 + to_thread 线程池），
Validator 对同维度多来源做冲突仲裁，取消/预算贯穿各 await 边界。
同步 run() 保持原有顺序语义（回归安全网）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from competitor_agent.analyzers.registry import AnalyzerRegistry
from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.config.loader import OrchestrationConfig
from competitor_agent.core.checkpoint import is_cancelled, set_cancel
from competitor_agent.core.freshness_gate import FreshnessGate
from competitor_agent.core.report_builder import ReportBuilder
from competitor_agent.core.source_dedup import SourceDedup
from competitor_agent.core.strategic_loop import StrategicPlanner
from competitor_agent.domain_types.conflict import CrossDimensionConflict
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult
from competitor_agent.domain_types.strategy import CompetitorStrategy
from competitor_agent.interfaces.collector import ICompetitorDataSource
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.llm.client import LLMClient
from competitor_agent.memory.timeline_memory import TimelineEvent
from competitor_agent.team.analyzer_agent import AnalyzerAgent
from competitor_agent.team.base_agent import AgentContext, AgentResult, AgentStatus
from competitor_agent.team.collector_agent import CollectorAgent
from competitor_agent.team.message_bus import T_ANALYZED, T_COLLECTED, T_VALIDATED, MessageBus
from competitor_agent.team.reporter_agent import ReporterAgent
from competitor_agent.team.reviewer_agent import ReviewResult, ReviewerAgent
from competitor_agent.team.validator_agent import FactValidator, ValidationResult, ValidatorAgent

logger = logging.getLogger("competitor_agent.team.orchestrator")

# 跨 Agent 等待上限（秒）：超时记 DEGRADED，不阻塞流水线（设计文档 33 §3.1）
COLLECT_TIMEOUT = 300.0
ANALYZE_TIMEOUT = 300.0
# 对抗式评审回灌修订上限（设计文档 49 §3.3）：有界循环，不破坏 47 调用次数不变量
_MAX_REVISION_ROUNDS = 1


class TeamOrchestrator:
    """多 Agent 流水线协调器（事件驱动 + 状态决策）"""

    def __init__(
        self,
        extractor: ICompetitorDataSource,
        bus: MessageBus | None = None,
        llm: LLMClient | None = None,
        use_llm: bool = False,
        memory: IFourLayerMemory | None = None,
        max_retries: int = 1,
        max_parallel: int = 4,
        ingester: Any | None = None,
        retriever: Any | None = None,
        session_id: str | None = None,
        providers: dict[str, object] | None = None,
        builder: ReportBuilder | None = None,
        selector: SourceSelector | None = None,
        tool_dispatcher: Any | None = None,  # 设计文档 44：链式分析工具补证分发器
        orchestration: OrchestrationConfig | None = None,  # 领域差异化编排开关（设计文档 49）
        freshness_gate: FreshnessGate | None = None,  # 新鲜度驱动委派（None → 原行为）
        archive_results: list | None = None,  # 归档结论（新鲜维度复用）
        archive_freshness: dict[str, float] | None = None,  # 归档维度年龄（天）
        timeline_events: list[TimelineEvent] | None = None,  # 时间线变更事件（提权重采）
        dedup: SourceDedup | None = None,  # 跨竞品同源去重（None → 原行为）
    ) -> None:
        self._bus = bus or MessageBus()
        self._planner = StrategicPlanner(llm=llm, use_llm=use_llm)
        # 设计文档 45：复用外层注入的 selector（含 L4 成功率 + 失败反例降级），缺省内部 new 兼容旧调用
        self._collector = CollectorAgent(
            self._bus,
            selector or SourceSelector(providers=list((providers or {}).values())),
            extractor,
            memory=memory,
            ingester=ingester,
            session_id=session_id,
            providers=providers,
            dedup=dedup,
        )
        self._analyzer = AnalyzerAgent(
            self._bus,
            AnalyzerRegistry(llm=llm, use_llm=use_llm, tool_dispatcher=tool_dispatcher),
            memory=memory,
            retriever=retriever,
        )
        self._validator = ValidatorAgent(self._bus, FactValidator(), memory=memory)
        # 复用外层 ReportBuilder（含 freshness TTL），使 team 报告带新鲜度元数据（设计文档 26）
        self._reporter = ReporterAgent(self._bus, builder or ReportBuilder(), memory=memory)
        self._memory = memory
        self._max_retries = max_retries
        self._max_parallel = max(1, int(max_parallel))
        self._session_id = session_id or ""
        self._subscribers_ready = False
        # ── 领域差异化编排（设计文档 49）──
        self._orchestration = orchestration or OrchestrationConfig()
        # 对抗式评审第 5 角色：默认关（reviewer.enabled），开才插入
        self._reviewer: ReviewerAgent | None = None
        if self._orchestration.reviewer_enabled:
            self._reviewer = ReviewerAgent(self._bus, memory=memory, tool_dispatcher=tool_dispatcher)
        # 新鲜度驱动委派：默认关（freshness_delegation.enabled）且需外部装配 FreshnessGate
        if self._orchestration.freshness_delegation_enabled and freshness_gate is not None:
            self._freshness_gate = freshness_gate
            self._archive_results = list(archive_results or [])
            self._archive_freshness = dict(archive_freshness or {})
            self._timeline_events = list(timeline_events or [])
        else:
            self._freshness_gate = None
            self._archive_results = []
            self._archive_freshness = {}
            self._timeline_events = []

    def cancel(self, session_id: str) -> None:
        """请求取消运行中的异步流水线（协作式取消，各 await 边界生效）"""
        set_cancel(session_id)
        logger.info("已请求取消异步会话: %s", session_id)

    @property
    def bus(self) -> MessageBus:
        return self._bus

    def run(self, task: str, strategy: CompetitorStrategy | None = None) -> CompetitorReport:
        """执行一条竞品分析任务，产出草稿报告（事件驱动 + 状态决策）。

        strategy 缺省时内部规划（保持旧调用契约）；由外层统一规划时传入复用，
        使 team 与 single 共享同一策略与规划埋点（设计文档 18）。
        """
        if strategy is None:
            strategy = self._planner.plan(task, memory=self._memory)
        if self._is_cancelled():
            logger.info("会话 %s 已取消，提前终止多 Agent 流水线", self._session_id)
            return self._partial_report(strategy, [], "分析已取消")
        ctx = AgentContext(
            task=task,
            strategy=strategy,
            session_id=self._session_id,
            max_retries=self._max_retries,
        )

        # 1. Collector：采集观测（新鲜度驱动委派：新鲜维度跳过采集复用归档，设计文档 49 §3.2）
        collect_strategy, fresh_results = self._collect_plan(strategy)
        if collect_strategy is None:
            observations: list = []
        else:
            collect = self._run_with_retry(self._collector, self._ctx_with_strategy(ctx, collect_strategy))
            if self._is_cancelled():
                return self._partial_report(strategy, fresh_results, "分析已取消")
            if collect.status == AgentStatus.FAILED:
                return self._empty_report(strategy, "采集失败: " + collect.reason)
            observations = collect.payload or []
        ctx.extra["observations"] = observations

        # 2. Analyzer：分析维度结论（合并新鲜维度归档结果）
        analyze = self._run_with_retry(self._analyzer, ctx)
        if self._is_cancelled():
            return self._partial_report(strategy, fresh_results + (analyze.payload or []), "分析已取消")
        if analyze.status == AgentStatus.FAILED:
            return self._empty_report(strategy, "分析失败: " + analyze.reason)
        results = list(analyze.payload or []) + fresh_results
        ctx.extra["results"] = results

        # 3. Validator：同维度多来源仲裁（真协作，设计文档 33 §3.3）+ 跨维度冲突检测（49 §3.1）→ 事实校验
        results = list(self._validator.arbitrate(results).values())
        ctx.extra["results"] = results
        cross_dim_conflicts = self._detect_cross_dimension_conflicts(results)
        ctx.extra["cross_dimension_conflicts"] = cross_dim_conflicts
        validate = self._run_with_retry(self._validator, ctx)
        if self._is_cancelled():
            return self._partial_report(strategy, results, "分析已取消")
        if validate.status == AgentStatus.FAILED:
            return self._empty_report(strategy, "校验失败: " + validate.reason)
        validation = validate.payload
        ctx.extra["validation"] = validation

        # 3.5 Reviewer：对抗式评审 + 回灌修订（≤1 轮，默认关，设计文档 49 §3.3）
        review, results = self._review_sync(ctx, results, observations, cross_dim_conflicts)
        ctx.extra["review"] = review
        ctx.extra["results"] = results  # 修订后结论回写，供 Reporter 汇总最新版本

        # 4. Reporter：汇总草稿报告
        report_result = self._run_with_retry(self._reporter, ctx)
        if self._is_cancelled():
            return self._partial_report(strategy, results, "分析已取消")
        if report_result.status == AgentStatus.FAILED or report_result.payload is None:
            return self._empty_report(strategy, "汇总失败: " + report_result.reason)
        return report_result.payload

    # ── 真异步协作编排（设计文档 33）─────────────────────────────────

    async def run_async(
        self, task: str, strategy: CompetitorStrategy | None = None
    ) -> CompetitorReport:
        """异步并行编排：Collector 总线驱动 → Analyzer 按缺口并行 → Validator 仲裁 → Reporter。

        各 await 边界做协作式取消检查；预算由外层（facade）统一记账，语义与同步路径一致。
        """
        if strategy is None:
            strategy = cast(
                CompetitorStrategy,
                await asyncio.to_thread(self._planner.plan, task, memory=self._memory),
            )
        if self._is_cancelled():
            logger.info("会话 %s 已取消，提前终止异步多 Agent 流水线", self._session_id)
            return self._partial_report(strategy, [], "分析已取消")
        ctx = AgentContext(
            task=task,
            strategy=strategy,
            session_id=self._session_id,
            max_retries=self._max_retries,
        )
        self._ensure_subscribers()

        # 1. Collector：总线请求/响应采集（await_result=True 拿观测，超时降级；
        #    新鲜度驱动委派：新鲜维度跳过采集复用归档，设计文档 49 §3.2）
        collect_strategy, fresh_results = self._collect_plan(strategy)
        if collect_strategy is None:
            observations: list = []
        else:
            observations = await self._collect_async(ctx, collect_strategy)
        if self._is_cancelled():
            return self._partial_report(strategy, fresh_results, "分析已取消")
        if not observations and not fresh_results:
            return self._empty_report(strategy, "采集失败: 无观测数据")
        ctx.extra["observations"] = observations

        # 2. Analyzer：按缺口并行分析（Semaphore 限流 + to_thread 线程池），合并新鲜维度归档结果
        results = await self._analyze_parallel(ctx, observations)
        results = list(results) + fresh_results
        if self._is_cancelled():
            return self._partial_report(strategy, results, "分析已取消")
        if not results:
            return self._empty_report(strategy, "分析失败: 观测未产出维度结论")
        ctx.extra["results"] = results

        # 3. Validator：同维度多来源仲裁 + 跨维度冲突检测（49 §3.1）+ 事实校验
        if self._is_cancelled():
            return self._partial_report(strategy, results, "分析已取消")
        arbitrated = self._validator.arbitrate(results)
        arbitrated_list = list(arbitrated.values())
        cross_dim_conflicts = self._detect_cross_dimension_conflicts(arbitrated_list)
        validation = self._validator.validate(strategy.competitor.name, arbitrated_list)
        self._bus.publish(
            T_VALIDATED,
            {
                "competitor": strategy.competitor.name,
                "results": arbitrated_list,
                "validation": validation,
            },
        )
        ctx.extra["results"] = arbitrated_list
        ctx.extra["validation"] = validation
        ctx.extra["cross_dimension_conflicts"] = cross_dim_conflicts

        # 3.5 Reviewer：对抗式评审 + 回灌修订（≤1 轮，默认关，设计文档 49 §3.3）
        review, arbitrated_list = await self._review_async(
            ctx, arbitrated_list, observations, cross_dim_conflicts
        )
        ctx.extra["review"] = review

        # 4. Reporter：汇总草稿报告（含仲裁/跨维度冲突/评审标注）
        if self._is_cancelled():
            return self._partial_report(strategy, arbitrated_list, "分析已取消")
        return self._reporter.draft(
            competitor=strategy.competitor,
            results=arbitrated_list,
            validation=validation,
            gaps_pending=[g for g in strategy.gaps if not g.is_closed],
            cross_dimension_conflicts=cross_dim_conflicts,
            review=review,
        )

    def _ensure_subscribers(self) -> None:
        """幂等注册异步订阅者（总线驱动编排；外部复用 bus 时仅注册一次）"""
        if self._subscribers_ready:
            return
        self._bus.subscribe_async(T_COLLECTED, self._collector._handle_async)
        self._bus.subscribe_async(T_ANALYZED, self._analyzer._handle_async)
        self._subscribers_ready = True

    async def _collect_async(self, ctx: AgentContext, strategy: CompetitorStrategy) -> list:
        """采集请求：失败（无观测）按剩余重试次数重发，超时/异常记 DEGRADED。"""
        attempts = 0
        while True:
            result = await self._bus.publish_async(
                T_COLLECTED,
                {"strategy": strategy},
                await_result=True,
                timeout=COLLECT_TIMEOUT,
            )
            payload = self._first_result(result)
            observations = (payload or {}).get("observations") or []
            if observations or attempts >= self._max_retries:
                return observations
            attempts += 1
            logger.warning("异步采集无观测，重试（第 %d/%d 次）", attempts, self._max_retries)

    async def _analyze_parallel(
        self, ctx: AgentContext, observations: list
    ) -> list[DimensionResult]:
        """按缺口并行分析：每个观测独立请求，Semaphore 限流并发度。"""
        sem = asyncio.Semaphore(self._max_parallel)
        competitor = ctx.strategy.competitor.name

        async def bounded(obs: Any) -> DimensionResult | None:
            if self._is_cancelled():
                return None
            async with sem:
                return await self._analyze_one(ctx, obs)

        done = await asyncio.gather(*[bounded(o) for o in observations])
        results = [r for r in done if isinstance(r, DimensionResult)]
        # 审计记录（异步订阅者不发布，由编排器统一收口，与同步路径 T_ANALYZED 对齐）
        self._bus.publish(T_ANALYZED, {"competitor": competitor, "results": results})
        return results

    async def _analyze_one(self, ctx: AgentContext, obs: Any) -> DimensionResult | None:
        """单观测分析请求（评审修订回灌复用，设计文档 49 §3.3）。"""
        result = await self._bus.publish_async(
            T_ANALYZED,
            {"competitor": ctx.strategy.competitor.name, "observation": obs},
            await_result=True,
            timeout=ANALYZE_TIMEOUT,
        )
        return self._first_result(result)

    # ── 领域差异化编排（设计文档 49）────────────────────────────────

    def _collect_plan(
        self, strategy: CompetitorStrategy
    ) -> tuple[CompetitorStrategy | None, list[DimensionResult]]:
        """新鲜度驱动委派：新鲜维度跳过采集，直接复用归档结论（49 §3.2）。

        返回 ``(collect_strategy, fresh_results)``：collect_strategy=None 表示全部新鲜
        （无采集任务）；未装配 FreshnessGate 时原样返回 (strategy, [])（零行为变化）。
        """
        if self._freshness_gate is None:
            return strategy, []
        decisions = self._freshness_gate.decide(
            strategy.gaps, self._archive_freshness, self._timeline_events
        )
        fresh_dims = set(decisions.fresh_dimensions())
        if not fresh_dims:
            return strategy, []
        fresh_results = [r for r in self._archive_results if r.dimension in fresh_dims]
        collect_gaps = [g for g in strategy.gaps if g.field not in fresh_dims]
        if not collect_gaps:
            return None, fresh_results
        collect_strategy = CompetitorStrategy(
            competitor=strategy.competitor,
            gaps=collect_gaps,
            budget_allocation=strategy.budget_allocation,
            terminal_thresholds=strategy.terminal_thresholds,
        )
        return collect_strategy, fresh_results

    @staticmethod
    def _ctx_with_strategy(ctx: AgentContext, strategy: CompetitorStrategy) -> AgentContext:
        """用替换策略的新上下文（新鲜度委派下 Collector 只采集非新鲜缺口）。"""
        return AgentContext(
            task=ctx.task,
            strategy=strategy,
            session_id=ctx.session_id,
            max_retries=ctx.max_retries,
            extra=dict(ctx.extra),
        )

    def _detect_cross_dimension_conflicts(
        self, results: list[DimensionResult]
    ) -> list[CrossDimensionConflict]:
        """跨维度冲突检测（默认开，无副作用）；失败静默降级为无冲突。"""
        if not self._orchestration.cross_dimension_conflict_enabled:
            return []
        try:
            return self._validator.detect_cross_dimension_conflicts(results)
        except Exception:  # noqa: BLE001 — 冲突检测失败不影响主流程
            logger.warning("跨维度冲突检测失败，跳过", exc_info=True)
            return []

    def _review_sync(
        self,
        ctx: AgentContext,
        results: list[DimensionResult],
        observations: list,
        cross_dim_conflicts: list[CrossDimensionConflict],
    ) -> tuple[ReviewResult | None, list[DimensionResult]]:
        """同步评审：对抗式证伪 → needs_revision 命中维度重入分析器修订（≤1 轮）→ 强制复查。

        未装配 Reviewer（默认关）→ 返回 (None, results)（零行为变化）。
        """
        if self._reviewer is None:
            return None, results
        verdict = self._reviewer.review(ctx, results, observations, cross_dim_conflicts)
        if verdict.ok:
            return ReviewResult(ok=True), results
        rounds = 0
        for _round in range(1, _MAX_REVISION_ROUNDS + 1):
            revise_dims = {i.dimension for i in verdict.issues}
            revised = [r for r in results if r.dimension not in revise_dims]
            sub_obs = [o for o in observations if getattr(o, "gap_field", None) in revise_dims]
            if sub_obs:
                sub_ctx = self._ctx_with_strategy(ctx, ctx.strategy)
                sub_ctx.extra["observations"] = sub_obs
                sub_ctx.extra["results"] = []
                outcome = self._run_with_retry(self._analyzer, sub_ctx)
                if outcome.ok and outcome.payload:
                    revised.extend(outcome.payload)
            results = list(self._validator.arbitrate(revised).values())
            rounds = _round
            verdict = self._reviewer.review(ctx, results, observations, cross_dim_conflicts)
            if verdict.ok:
                return ReviewResult(ok=True, revised=True, rounds=rounds), results
        return (
            ReviewResult(ok=False, issues=verdict.issues, revised=True, rounds=rounds),
            results,
        )

    async def _review_async(
        self,
        ctx: AgentContext,
        results: list[DimensionResult],
        observations: list,
        cross_dim_conflicts: list[CrossDimensionConflict],
    ) -> tuple[ReviewResult | None, list[DimensionResult]]:
        """异步评审（语义与同步一致）：证伪 → 命中维度重入分析器修订（≤1 轮）→ 强制复查。"""
        if self._reviewer is None:
            return None, results
        verdict = self._reviewer.review(ctx, results, observations, cross_dim_conflicts)
        if verdict.ok:
            return ReviewResult(ok=True), results
        rounds = 0
        for _round in range(1, _MAX_REVISION_ROUNDS + 1):
            revise_dims = {i.dimension for i in verdict.issues}
            revised = [r for r in results if r.dimension not in revise_dims]
            for obs in observations:
                if getattr(obs, "gap_field", None) in revise_dims:
                    new_result = await self._analyze_one(ctx, obs)
                    if new_result is not None:
                        revised.append(new_result)
            results = list(self._validator.arbitrate(revised).values())
            rounds = _round
            verdict = self._reviewer.review(ctx, results, observations, cross_dim_conflicts)
            if verdict.ok:
                return ReviewResult(ok=True, revised=True, rounds=rounds), results
        return (
            ReviewResult(ok=False, issues=verdict.issues, revised=True, rounds=rounds),
            results,
        )

    @staticmethod
    def _first_result(value: Any) -> Any:
        """publish_async 返回订阅者产出列表，取首个有效结果。"""
        if isinstance(value, list):
            return next((v for v in value if v is not None), None)
        return value

    def _is_cancelled(self) -> bool:
        """会话被取消（协作式取消：流水线各阶段边界检查，而非静待线程结束）"""
        return bool(self._session_id) and is_cancelled(self._session_id)

    def _run_with_retry(self, agent: Any, ctx: AgentContext) -> AgentResult:
        """执行 Agent，遇 RETRY 按剩余次数重试。"""
        result = agent.run(ctx)
        while result.status == AgentStatus.RETRY and ctx.max_retries > 0:
            ctx.max_retries -= 1
            logger.warning("[%s] 重试执行（剩余 %d 次）", agent.name, ctx.max_retries)
            result = agent.run(ctx)
        return result

    def _empty_report(self, strategy: CompetitorStrategy, reason: str) -> CompetitorReport:
        """流水线失败时返回空报告（含失败原因）。"""
        logger.error("多 Agent 流水线失败: %s", reason)
        return self._reporter.draft(
            competitor=strategy.competitor,
            results=[],
            validation=ValidationResult(passed=False, issues=[]),
            gaps_pending=list(strategy.gaps),
        )

    def _partial_report(
        self, strategy: CompetitorStrategy, results: list, reason: str
    ) -> CompetitorReport:
        """取消/中断时返回部分结果报告（不视为失败）。"""
        logger.info("多 Agent 流水线中断: %s（保留 %d 个维度结果）", reason, len(results))
        return self._reporter.draft(
            competitor=strategy.competitor,
            results=results,
            validation=ValidationResult(passed=False, issues=[]),
            gaps_pending=list(strategy.gaps),
        )
