"""TeamOrchestrator — 多 Agent 流水线编排

一条任务：CollectorAgent → AnalyzerAgent → ValidatorAgent → ReporterAgent，
结构化 Artifact 经 MessageBus 传递，最终产出草稿报告。
"""
from __future__ import annotations

import logging

from competitor_agent.analyzers.registry import AnalyzerRegistry
from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.core.strategic_loop import StrategicPlanner
from competitor_agent.domain_types.report import CompetitorReport
from competitor_agent.interfaces.collector import ICompetitorDataSource
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.llm.client import LLMClient
from competitor_agent.team.analyzer_agent import AnalyzerAgent
from competitor_agent.team.collector_agent import CollectorAgent
from competitor_agent.team.message_bus import MessageBus
from competitor_agent.team.reporter_agent import ReporterAgent
from competitor_agent.team.validator_agent import FactValidator, ValidatorAgent

logger = logging.getLogger("competitor_agent.team.orchestrator")


class TeamOrchestrator:
    """多 Agent 流水线协调器"""

    def __init__(
        self,
        extractor: ICompetitorDataSource,
        bus: MessageBus | None = None,
        llm: LLMClient | None = None,
        use_llm: bool = False,
        memory: IFourLayerMemory | None = None,
    ) -> None:
        self._bus = bus or MessageBus()
        self._planner = StrategicPlanner()
        self._collector = CollectorAgent(self._bus, SourceSelector(), extractor)
        self._analyzer = AnalyzerAgent(self._bus, AnalyzerRegistry(llm=llm, use_llm=use_llm))
        self._validator = ValidatorAgent(self._bus, FactValidator())
        self._reporter = ReporterAgent(self._bus, memory=memory)
        self._memory = memory

    @property
    def bus(self) -> MessageBus:
        return self._bus

    def run(self, task: str) -> CompetitorReport:
        """执行一条竞品分析任务，产出草稿报告。"""
        strategy = self._planner.plan(task, memory=self._memory)

        observations = self._collector.collect(strategy)
        results = self._analyzer.analyze(strategy.competitor.name, observations)
        validation = self._validator.validate(strategy.competitor.name, results)
        report = self._reporter.draft(
            competitor=strategy.competitor,
            results=results,
            validation=validation,
            gaps_pending=[g for g in strategy.gaps if not g.is_closed],
        )
        return report