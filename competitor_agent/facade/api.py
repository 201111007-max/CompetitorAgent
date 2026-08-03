"""CompetitorAnalysisAPI — 外部唯一入口

组装：StrategicLoop（规划）→ 逐缺口 TacticalLoop（采集+分析）
     → BudgetController（终止）→ ReportBuilder（汇总）
M1 默认 LLM 关闭（use_llm=False），无 Key 也能产出报告（规则降级）。
"""
from __future__ import annotations

import logging
from typing import Callable

from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.agent.react_loop import ReactLoop
from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.analyzers.registry import AnalyzerRegistry
from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.collector.web_extractor import WebExtractor
from competitor_agent.core.budget import IterationBudget
from competitor_agent.core.budget_controller import BudgetController, StopReason
from competitor_agent.core.report_builder import ReportBuilder
from competitor_agent.core.stop_verifier import StopVerifier
from competitor_agent.core.strategic_loop import StrategicPlanner
from competitor_agent.core.tactical_loop import TacticalLoop
from competitor_agent.domain_types.enums import TerminalState
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult
from competitor_agent.domain_types.strategy import CompetitorStrategy
from competitor_agent.interfaces.context import Skill
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.llm.client import LLMClient

logger = logging.getLogger("competitor_agent.facade.api")


class CompetitorAnalysisAPI:
    """竞品分析外部入口"""

    def __init__(
        self,
        llm: LLMClient | None = None,
        use_llm: bool = False,
        max_iterations: int = 10,
        cost_limit: float = 1.0,
        event_sink: Callable[[ProgressEvent], None] | None = None,
        extractor: WebExtractor | None = None,
        memory: IFourLayerMemory | None = None,
    ) -> None:
        self._llm = llm
        self._use_llm = use_llm
        self._event_sink = event_sink
        self._memory = memory

        self._planner = StrategicPlanner()
        self._selector = SourceSelector()
        if memory is not None:
            self._selector.set_success_rates(memory.source_success_rates())
        self._extractor = extractor or WebExtractor()
        self._analyzers = AnalyzerRegistry(llm=llm, use_llm=use_llm)
        self._builder = ReportBuilder()
        self._budget = BudgetController(max_iterations=max_iterations, cost_limit=cost_limit)
        self._verifier = StopVerifier()

    def analyze(self, task: str) -> CompetitorReport:
        """单竞品分析：输入任务文本 → CompetitorReport"""
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

        for gap in strategy.gaps:
            if self._budget.should_stop(strategy.gaps).should_stop:
                break
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
            )
            result = loop.execute(gap, strategy)
            if result is not None:
                results.append(result)
                self._record_memory_success(strategy, gap)
            self._budget.record_iteration(cost=0.01)

        stop = self._budget.should_stop(strategy.gaps)
        pending = [g for g in strategy.gaps if not g.is_closed]
        terminal = self._terminal_state(stop.reason, strategy)

        report = self._builder.build(
            competitor=strategy.competitor,
            results=results,
            gaps_pending=pending,
            terminal_state=terminal.value,
        )
        self._emit(
            ProgressEvent(
                event="report",
                phase="report",
                progress=1.0,
                message=f"报告生成完成，终态={terminal.value}",
            )
        )
        return report

    @property
    def memory(self) -> IFourLayerMemory | None:
        return self._memory

    def analyze_react(self, task: str) -> str:
        """ReAct 模式：LLM 驱动工具调用（需 LLM Key）"""
        dispatcher = ToolDispatcher()
        dispatcher.register(
            "web_extract",
            lambda url: f"web_extract(url={url}) 已请求",
        )
        agent = ReactAgent(llm=self._llm or LLMClient(), dispatcher=dispatcher)
        loop = ReactLoop(agent, event_sink=self._event_sink)
        return loop.run(task)

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