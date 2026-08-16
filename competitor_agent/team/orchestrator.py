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
from competitor_agent.core.checkpoint import is_cancelled, set_cancel
from competitor_agent.core.report_builder import ReportBuilder
from competitor_agent.core.strategic_loop import StrategicPlanner
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult
from competitor_agent.domain_types.strategy import CompetitorStrategy
from competitor_agent.interfaces.collector import ICompetitorDataSource
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.llm.client import LLMClient
from competitor_agent.team.analyzer_agent import AnalyzerAgent
from competitor_agent.team.base_agent import AgentContext, AgentResult, AgentStatus
from competitor_agent.team.collector_agent import CollectorAgent
from competitor_agent.team.message_bus import T_ANALYZED, T_COLLECTED, T_VALIDATED, MessageBus
from competitor_agent.team.reporter_agent import ReporterAgent
from competitor_agent.team.validator_agent import FactValidator, ValidationResult, ValidatorAgent

logger = logging.getLogger("competitor_agent.team.orchestrator")

# 跨 Agent 等待上限（秒）：超时记 DEGRADED，不阻塞流水线（设计文档 33 §3.1）
COLLECT_TIMEOUT = 300.0
ANALYZE_TIMEOUT = 300.0


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

        # 1. Collector：采集观测
        collect = self._run_with_retry(self._collector, ctx)
        if self._is_cancelled():
            return self._partial_report(strategy, [], "分析已取消")
        if collect.status == AgentStatus.FAILED:
            return self._empty_report(strategy, "采集失败: " + collect.reason)
        observations = collect.payload or []
        ctx.extra["observations"] = observations

        # 2. Analyzer：分析维度结论
        analyze = self._run_with_retry(self._analyzer, ctx)
        if self._is_cancelled():
            return self._partial_report(strategy, [], "分析已取消")
        if analyze.status == AgentStatus.FAILED:
            return self._empty_report(strategy, "分析失败: " + analyze.reason)
        results = analyze.payload or []
        ctx.extra["results"] = results

        # 3. Validator：同维度多来源仲裁（真协作，设计文档 33 §3.3）→ 事实校验
        results = list(self._validator.arbitrate(results).values())
        ctx.extra["results"] = results
        validate = self._run_with_retry(self._validator, ctx)
        if self._is_cancelled():
            return self._partial_report(strategy, results, "分析已取消")
        if validate.status == AgentStatus.FAILED:
            return self._empty_report(strategy, "校验失败: " + validate.reason)
        validation = validate.payload
        ctx.extra["validation"] = validation

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

        # 1. Collector：总线请求/响应采集（await_result=True 拿观测，超时降级）
        observations = await self._collect_async(ctx, strategy)
        if self._is_cancelled():
            return self._partial_report(strategy, [], "分析已取消")
        if not observations:
            return self._empty_report(strategy, "采集失败: 无观测数据")
        ctx.extra["observations"] = observations

        # 2. Analyzer：按缺口并行分析（Semaphore 限流 + to_thread 线程池）
        results = await self._analyze_parallel(ctx, observations)
        if self._is_cancelled():
            return self._partial_report(strategy, results, "分析已取消")
        if not results:
            return self._empty_report(strategy, "分析失败: 观测未产出维度结论")
        ctx.extra["results"] = results

        # 3. Validator：同维度多来源仲裁 + 事实校验
        if self._is_cancelled():
            return self._partial_report(strategy, results, "分析已取消")
        arbitrated = self._validator.arbitrate(results)
        arbitrated_list = list(arbitrated.values())
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

        # 4. Reporter：汇总草稿报告（含仲裁冲突标注）
        if self._is_cancelled():
            return self._partial_report(strategy, arbitrated_list, "分析已取消")
        return self._reporter.draft(
            competitor=strategy.competitor,
            results=arbitrated_list,
            validation=validation,
            gaps_pending=[g for g in strategy.gaps if not g.is_closed],
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
                result = await self._bus.publish_async(
                    T_ANALYZED,
                    {"competitor": competitor, "observation": obs},
                    await_result=True,
                    timeout=ANALYZE_TIMEOUT,
                )
            return self._first_result(result)

        done = await asyncio.gather(*[bounded(o) for o in observations])
        results = [r for r in done if isinstance(r, DimensionResult)]
        # 审计记录（异步订阅者不发布，由编排器统一收口，与同步路径 T_ANALYZED 对齐）
        self._bus.publish(T_ANALYZED, {"competitor": competitor, "results": results})
        return results

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
