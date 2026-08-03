"""SubAgent — 子代理（M3 3.6 并行执行单元）

封装单缺口闭环：一个子代理负责一个 InfoGap 的采集+分析。
可与 ParallelRunner 配合并发执行多个独立缺口。
"""
from __future__ import annotations

from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.collector.source_selector import SourceCandidate, SourceSelector
from competitor_agent.core.budget import IterationBudget
from competitor_agent.domain_types.enums import GapStatus, ObservationStatus
from competitor_agent.domain_types.info_gap import CLOSED_CONFIDENCE, InfoGap
from competitor_agent.domain_types.observation import Observation
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.domain_types.strategy import CompetitorStrategy
from competitor_agent.interfaces.collector import ICompetitorDataSource
from competitor_agent.interfaces.context import AnalysisContext, SourceContext
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError
from competitor_agent.observability.logger import get_logger

logger = get_logger("core.subagent")


class SubAgent:
    """单缺口子代理：选源→采集→分析→更新缺口状态"""

    def __init__(
        self,
        gap: InfoGap,
        strategy: CompetitorStrategy,
        selector: SourceSelector,
        extractor: ICompetitorDataSource,
        analyzer: BaseCompetitorAnalyzer,
        budget: IterationBudget,
    ) -> None:
        self._gap = gap
        self._strategy = strategy
        self._selector = selector
        self._extractor = extractor
        self._analyzer = analyzer
        self._budget = budget

    @property
    def field(self) -> str:
        return self._gap.field

    @property
    def gap(self) -> InfoGap:
        return self._gap

    def run(self) -> DimensionResult | None:
        """执行单缺口闭环，返回维度结论（失败返回 None）。"""
        context = SourceContext(competitor_name=self._strategy.competitor.name)
        for candidate in self._selector.candidates(self._gap, self._strategy.competitor):
            if not self._budget.consume(delta_cost=0.01):
                logger.warning("预算耗尽，缺口未闭环: %s", self._gap.field)
                self._gap.status = GapStatus.BLOCKED
                return None
            try:
                obs = self._collect(candidate, context)
            except DataSourceUnavailableError as exc:
                self._gap.record_source_try(candidate.source_name)
                logger.info("候选源失败 %s: %s", candidate.source_name, exc)
                continue
            self._gap.record_source_try(candidate.source_name)
            result = self._analyze(obs, context)
            self._update_gap(obs, result)
            return result
        self._gap.status = GapStatus.BLOCKED
        return None

    def _collect(self, candidate: SourceCandidate, context: SourceContext) -> Observation:
        return self._extractor.fetch(
            self._gap,
            SourceContext(
                competitor_name=context.competitor_name,
                query=self._gap.field,
                kwargs={"url": candidate.url},
            ),
        )

    def _analyze(self, obs: Observation, context: SourceContext) -> DimensionResult:
        return self._analyzer.analyze(
            obs,
            self._gap,
            AnalysisContext(
                competitor_name=context.competitor_name,
                dimension=self._analyzer.dimension,
            ),
        )

    def _update_gap(self, obs: Observation, result: DimensionResult) -> None:
        self._gap.add_evidence(obs.evidence)
        self._gap.confidence = max(self._gap.confidence, result.confidence)
        if obs.status == ObservationStatus.OK and result.confidence >= CLOSED_CONFIDENCE:
            self._gap.status = GapStatus.CONFIRMED
        elif self._gap.confidence > 0:
            self._gap.status = GapStatus.PARTIAL