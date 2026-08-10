"""TacticalLoop — 单缺口闭环：预算→选源→采集→分析→置信度更新

流程（对照架构文档 5.2）：
1. budget.consume()
2. SourceSelector 给候选源（降级链）
3. collector.fetch → Observation
4. analyzer.analyze → 更新缺口置信度 + 证据
5. 多源一致/置信达标 → CONFIRMED/CLOSED；失败 → 记录并换降级源
"""
from __future__ import annotations

from typing import Any

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
        ingester: Any | None = None,
        retriever: Any | None = None,
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
        # RAG 知识库（可选）：采集后摄入 + 分析前检索注入
        self._ingester = ingester
        self._retriever = retriever

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
            self._ingest_observation(observation, strategy.competitor.name, gap.field)
            result = self._analyze(observation, gap, context)
            self._update_gap(gap, observation, result)
            return result

        gap.status = GapStatus.BLOCKED
        return None

    def _ingest_observation(
        self, observation: Observation, competitor: str, dimension: str
    ) -> None:
        """采集到有效文本后摄入知识库（RAG 灌库链路）"""
        if self._ingester is None or not observation.raw_text.strip():
            return
        try:
            self._ingester.ingest(
                competitor=competitor,
                dimension=dimension,
                text=observation.raw_text,
                source_url=observation.evidence.url if observation.evidence else "",
            )
        except Exception:  # noqa: BLE001 — 摄入失败不影响主流程
            logger.warning("知识库摄入失败: %s/%s", competitor, dimension)

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
                rag_context=self._retrieve_rag(context.competitor_name, gap.field),
            ),
        )

    def _retrieve_rag(self, competitor: str, dimension: str) -> str:
        """检索知识库相关片段，拼成可注入的文本（含来源）"""
        if self._retriever is None:
            return ""
        try:
            chunks = self._retriever.retrieve(
                query=dimension,
                competitor=competitor,
                dimension=dimension,
                top_k=5,
            )
        except Exception:  # noqa: BLE001 — 检索失败不影响主流程
            logger.warning("知识库检索失败: %s/%s", competitor, dimension)
            return ""
        if not chunks:
            return ""
        lines = []
        for c in chunks:
            src = f"（来源: {c.source_url}）" if c.source_url else ""
            lines.append(f"- [{c.competitor}/{c.dimension}]{src} {c.text[:300]}")
        return "\n".join(lines)

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