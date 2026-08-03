"""TacticalLoop — 单缺口闭环：预算→选源→采集→分析→置信度更新

流程（对照架构文档 5.2）：
1. budget.consume()
2. SourceSelector 给候选源（降级链）
3. collector.fetch → Observation
4. analyzer.analyze → 更新缺口置信度 + 证据
5. 多源一致/置信达标 → CONFIRMED/CLOSED；失败 → 记录并换降级源
"""
from __future__ import annotations

from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.collector.source_selector import SourceCandidate, SourceSelector
from competitor_agent.collector.spa_extractor import SpaExtractor
from competitor_agent.collector.web_extractor import WebExtractor
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

logger = get_logger("core.tactical_loop")


class TacticalLoop:
    """针对单个 InfoGap 执行采集→分析闭环，输出该维度结论"""

    def __init__(
        self,
        selector: SourceSelector,
        extractor: WebExtractor,
        analyzer: BaseCompetitorAnalyzer,
        budget: IterationBudget,
        extractors: dict[str, ICompetitorDataSource] | None = None,
    ) -> None:
        self._selector = selector
        self._extractor = extractor
        self._analyzer = analyzer
        self._budget = budget
        # 按 source_name 分发的采集器注册表（SPA 兜底）；未注册的源回退到默认 extractor
        self._extractors: dict[str, ICompetitorDataSource] = dict(
            extractors
            or {
                "web_extractor": extractor,
                "spa_extractor": SpaExtractor(),
            }
        )

    def execute(self, gap: InfoGap, strategy: CompetitorStrategy) -> DimensionResult | None:
        """执行单缺口闭环。返回维度结论（失败返回 None）。"""
        context = SourceContext(competitor_name=strategy.competitor.name)
        candidates = self._selector.candidates(gap, strategy.competitor)

        for index, candidate in enumerate(candidates):
            if not self._budget.consume(delta_cost=0.01):
                logger.warning("预算耗尽，缺口未闭环: %s", gap.field)
                gap.status = GapStatus.BLOCKED
                return None

            try:
                observation = self._collect(candidate, gap, context)
            except DataSourceUnavailableError as exc:
                gap.record_source_try(candidate.source_name)
                logger.info("候选源失败 %s: %s", candidate.source_name, exc)
                continue

            gap.record_source_try(candidate.source_name)
            result = self._analyze(observation, gap, context)
            self._update_gap(gap, observation, result)
            return result

        gap.status = GapStatus.BLOCKED
        return None

    def _collect(
        self, candidate: SourceCandidate, gap: InfoGap, context: SourceContext
    ) -> Observation:
        ctx = SourceContext(
            competitor_name=context.competitor_name,
            query=gap.field,
            kwargs={"url": candidate.url},
        )
        extractor = self._extractors.get(candidate.source_name, self._extractor)
        return extractor.fetch(gap, ctx)

    def _analyze(
        self, observation: Observation, gap: InfoGap, context: SourceContext
    ) -> DimensionResult:
        return self._analyzer.analyze(
            observation,
            gap,
            AnalysisContext(
                competitor_name=context.competitor_name,
                dimension=self._analyzer.dimension,
            ),
        )

    def _update_gap(
        self, gap: InfoGap, observation: Observation, result: DimensionResult
    ) -> None:
        """合并证据、更新置信度与状态"""
        gap.add_evidence(observation.evidence)
        # 多证据取 max（官方源可信）与置信度加权
        gap.confidence = max(gap.confidence, result.confidence)
        if observation.status == ObservationStatus.OK and result.confidence >= CLOSED_CONFIDENCE:
            gap.status = GapStatus.CONFIRMED
        elif gap.confidence > 0:
            gap.status = GapStatus.PARTIAL