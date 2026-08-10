"""TeamOrchestrator — 多 Agent 流水线编排

一条任务：CollectorAgent → AnalyzerAgent → ValidatorAgent → ReporterAgent，
结构化 Artifact 经 MessageBus 传递，最终产出草稿报告。

编排基于 AgentResult 状态做决策：
- SUCCESS：正常进入下一环节
- DEGRADED：降级继续（记录原因）
- RETRY：按策略重试（有限次数）
- FAILED：终止流水线，返回失败
"""
from __future__ import annotations

import logging
from typing import Any

from competitor_agent.analyzers.registry import AnalyzerRegistry
from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.core.strategic_loop import StrategicPlanner
from competitor_agent.domain_types.report import CompetitorReport
from competitor_agent.interfaces.collector import ICompetitorDataSource
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.llm.client import LLMClient
from competitor_agent.team.analyzer_agent import AnalyzerAgent
from competitor_agent.team.base_agent import AgentContext, AgentResult, AgentStatus
from competitor_agent.team.collector_agent import CollectorAgent
from competitor_agent.team.message_bus import MessageBus
from competitor_agent.team.reporter_agent import ReporterAgent
from competitor_agent.team.validator_agent import FactValidator, ValidationResult, ValidatorAgent

logger = logging.getLogger("competitor_agent.team.orchestrator")


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
        ingester: Any | None = None,
        retriever: Any | None = None,
    ) -> None:
        self._bus = bus or MessageBus()
        self._planner = StrategicPlanner(llm=llm, use_llm=use_llm)
        self._collector = CollectorAgent(
            self._bus, SourceSelector(), extractor, memory=memory, ingester=ingester
        )
        self._analyzer = AnalyzerAgent(
            self._bus,
            AnalyzerRegistry(llm=llm, use_llm=use_llm),
            memory=memory,
            retriever=retriever,
        )
        self._validator = ValidatorAgent(self._bus, FactValidator(), memory=memory)
        self._reporter = ReporterAgent(self._bus, memory=memory)
        self._memory = memory
        self._max_retries = max_retries

    @property
    def bus(self) -> MessageBus:
        return self._bus

    def run(self, task: str) -> CompetitorReport:
        """执行一条竞品分析任务，产出草稿报告（事件驱动 + 状态决策）。"""
        strategy = self._planner.plan(task, memory=self._memory)
        ctx = AgentContext(
            task=task,
            strategy=strategy,
            max_retries=self._max_retries,
        )

        # 1. Collector：采集观测
        collect = self._run_with_retry(self._collector, ctx)
        if collect.status == AgentStatus.FAILED:
            return self._empty_report(strategy, "采集失败: " + collect.reason)
        observations = collect.payload or []
        ctx.extra["observations"] = observations

        # 2. Analyzer：分析维度结论
        analyze = self._run_with_retry(self._analyzer, ctx)
        if analyze.status == AgentStatus.FAILED:
            return self._empty_report(strategy, "分析失败: " + analyze.reason)
        results = analyze.payload or []
        ctx.extra["results"] = results

        # 3. Validator：校验结论
        validate = self._run_with_retry(self._validator, ctx)
        if validate.status == AgentStatus.FAILED:
            return self._empty_report(strategy, "校验失败: " + validate.reason)
        validation = validate.payload
        ctx.extra["validation"] = validation

        # 4. Reporter：汇总草稿报告
        report_result = self._run_with_retry(self._reporter, ctx)
        if report_result.status == AgentStatus.FAILED or report_result.payload is None:
            return self._empty_report(strategy, "汇总失败: " + report_result.reason)
        return report_result.payload

    def _run_with_retry(self, agent, ctx: AgentContext) -> AgentResult:
        """执行 Agent，遇 RETRY 按剩余次数重试。"""
        result = agent.run(ctx)
        while result.status == AgentStatus.RETRY and ctx.max_retries > 0:
            ctx.max_retries -= 1
            logger.warning("[%s] 重试执行（剩余 %d 次）", agent.name, ctx.max_retries)
            result = agent.run(ctx)
        return result

    def _empty_report(self, strategy, reason: str) -> CompetitorReport:
        """流水线失败时返回空报告（含失败原因）。"""
        logger.error("多 Agent 流水线失败: %s", reason)
        return self._reporter.draft(
            competitor=strategy.competitor,
            results=[],
            validation=ValidationResult(passed=False, issues=[]),
            gaps_pending=list(strategy.gaps),
        )
