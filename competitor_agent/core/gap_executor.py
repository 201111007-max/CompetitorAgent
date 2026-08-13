"""GapExecutor — 统一的单缺口闭环：选源→采集→降级→分析→更新缺口

原 TacticalLoop.execute / SubAgent.run 各自复制了同一套"选源→采集→降级→分析"
流程（问题 12.1），此处收敛为单一实现，供单 Agent 主路径（TacticalLoop）与
并行子代理（SubAgent）复用。

"选源→采集"环节的候选源分发（fetch_candidate）亦供多 Agent 的 CollectorAgent
复用，避免第三处复制。
"""

from __future__ import annotations

import time
from typing import Any

from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.collector.source_selector import SourceCandidate, SourceSelector
from competitor_agent.collector.spa_extractor import SpaExtractor
from competitor_agent.core.budget import IterationBudget
from competitor_agent.core.checkpoint import is_cancelled
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import GapStatus, ObservationStatus
from competitor_agent.domain_types.info_gap import CLOSED_CONFIDENCE, InfoGap
from competitor_agent.domain_types.observation import Observation
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.interfaces.collector import ICompetitorDataSource
from competitor_agent.interfaces.context import AnalysisContext, SourceContext
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError
from competitor_agent.observability.logger import get_logger, get_session_logger, log_event

logger = get_logger("core.gap_executor")

# 走默认 extractor 的候选 kind（官网/SPA/缓存）；其余 kind 走外部源 provider 分发
_WEB_KINDS = frozenset({"web", "spa", "cache"})


def fetch_candidate(
    gap: InfoGap,
    candidate: SourceCandidate,
    competitor: Competitor,
    default_extractor: ICompetitorDataSource,
    extractors: dict[str, ICompetitorDataSource] | None = None,
    providers: dict[str, object] | None = None,
) -> Observation:
    """按候选源抓取观测（设计文档 23 §3.3）。

    - `web` / `spa` / `cache`：按 source_name 分发到注册采集器，未注册回退默认；
    - `github` / `marketplace` / `benchmark` / `social`：查 provider 注册表（kind 索引）
      调用对应采集函数，失败抛 DataSourceUnavailableError 走降级链。

    供 GapExecutor._collect 与 CollectorAgent 共用，消除"构造 SourceContext +
    按源分发采集器"的重复。
    """
    if candidate.kind in _WEB_KINDS:
        extractor = default_extractor
        if extractors:
            extractor = extractors.get(candidate.source_name, default_extractor)
        return extractor.fetch(
            gap,
            SourceContext(
                competitor_name=competitor.name,
                query=gap.field,
                kwargs={"url": candidate.url},
            ),
        )
    provider = (providers or {}).get(candidate.kind)
    if provider is None:
        raise DataSourceUnavailableError(f"无 {candidate.kind} 类提供方，无法采集 {candidate.source_name}")
    return provider.fetch(gap, candidate, competitor)


class GapExecutor:
    """统一的单缺口闭环：预算/取消检查 → 选源→采集（失败降级）→ RAG → 分析 → 更新缺口。

    TacticalLoop（单 Agent 主路径）与 SubAgent（并行子代理）均委托本类完成闭环，
    保证各路径的采集/降级/分析行为完全一致（问题 12.1 消重）。
    """

    def __init__(
        self,
        selector: SourceSelector,
        extractor: ICompetitorDataSource,
        analyzer: BaseCompetitorAnalyzer,
        budget: IterationBudget,
        extractors: dict[str, ICompetitorDataSource] | None = None,
        ingester: Any | None = None,
        retriever: Any | None = None,
        session_id: str | None = None,
        providers: dict[str, object] | None = None,
    ) -> None:
        self._selector = selector
        self._default_extractor = extractor
        self._analyzer = analyzer
        self._budget = budget
        self._session_id = session_id
        # 按 source_name 分发的采集器注册表（SPA 兜底）；未注册的源回退到默认 extractor
        self._extractors: dict[str, ICompetitorDataSource] = dict(
            extractors
            or {
                "web_extractor": extractor,
                "spa_extractor": SpaExtractor(),
            }
        )
        # 外部源提供方（设计文档 23）：kind → provider，fetch_candidate 按 kind 分发
        self._providers: dict[str, object] = dict(providers or {})
        # RAG 知识库（可选）：采集后摄入 + 分析前检索注入
        self._ingester = ingester
        self._retriever = retriever

    @property
    def budget(self) -> IterationBudget:
        return self._budget

    def execute(self, gap: InfoGap, competitor: Competitor) -> DimensionResult | None:
        """执行单缺口闭环。返回维度结论（失败/被取消返回 None）。"""
        context = SourceContext(competitor_name=competitor.name)
        candidates = self._selector.candidates(gap, competitor)
        slog = get_session_logger(self._session_id)

        for candidate in candidates:
            if self._session_id and is_cancelled(self._session_id):
                logger.info("会话 %s 已取消，停止缺口 %s", self._session_id, gap.field)
                break
            if not self._budget.consume(delta_cost=0.01):
                logger.warning("预算耗尽，缺口未闭环: %s", gap.field)
                gap.status = GapStatus.BLOCKED
                return None

            log_event(
                slog, "source.selected", "select",
                f"缺口 {gap.field} 选源 {candidate.source_name}",
                gap_field=gap.field, source_name=candidate.source_name,
                url=candidate.url, degraded=(candidate.trust_level < 0.9),
            )
            started = time.monotonic()
            try:
                observation = self._collect(candidate, gap, context, competitor)
            except DataSourceUnavailableError as exc:
                gap.record_source_try(candidate.source_name)
                logger.info("候选源失败 %s: %s", candidate.source_name, exc)
                log_event(
                    slog, "collect.fail", "collect",
                    f"采集失败 {candidate.source_name}: {exc}",
                    gap_field=gap.field, source_name=candidate.source_name,
                    url=candidate.url, elapsed_ms=int((time.monotonic() - started) * 1000),
                )
                continue

            gap.record_source_try(candidate.source_name)
            elapsed = int((time.monotonic() - started) * 1000)
            log_event(
                slog, "collect.done", "collect",
                f"采集完成 {candidate.source_name}（{len(observation.raw_text)} 字节, {elapsed}ms）",
                gap_field=gap.field, source_name=candidate.source_name,
                url=candidate.url, bytes=len(observation.raw_text), elapsed_ms=elapsed,
            )
            self._ingest_observation(observation, competitor.name, gap.field)
            result = self._analyze(observation, gap, context)
            log_event(
                slog, "analyze.done", "analyze",
                f"分析完成 {gap.field}（置信度 {result.confidence:.2f}）",
                dimension=gap.field, confidence=round(result.confidence, 3),
                model=(getattr(self._analyzer, "_llm", None) and getattr(self._analyzer._llm, "_model", "")) or "rules",
            )
            self._update_gap(gap, observation, result)
            return result

        gap.status = GapStatus.BLOCKED
        return None

    def _collect(
        self, candidate: SourceCandidate, gap: InfoGap, context: SourceContext, competitor: Competitor
    ) -> Observation:
        return fetch_candidate(
            gap,
            candidate,
            competitor,
            self._default_extractor,
            self._extractors,
            self._providers,
        )

    def _ingest_observation(self, observation: Observation, competitor: str, dimension: str) -> None:
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

    def _analyze(self, observation: Observation, gap: InfoGap, context: SourceContext) -> DimensionResult:
        analysis_ctx = AnalysisContext(
            competitor_name=context.competitor_name,
            dimension=self._analyzer.dimension,
            rag_context=self._retrieve_rag(context.competitor_name, gap.field),
        )
        if gap.field == "performance":
            # 榜单直连（设计文档 25）：仅 performance 缺口注入，避免其余维度额外开销
            provider = self._providers.get("benchmark")
            if provider is not None:
                try:
                    analysis_ctx.benchmark_scores = provider.fetch_scores(context.competitor_name)  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001 — 榜单失败完全回退现状，不阻塞主流程
                    logger.warning("榜单直连失败，回退页面抽取: %s", context.competitor_name)
        return self._analyzer.analyze(observation, gap, analysis_ctx)

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

    def _update_gap(self, gap: InfoGap, observation: Observation, result: DimensionResult) -> None:
        """合并证据、更新置信度与状态"""
        gap.add_evidence(observation.evidence)
        # 多证据取 max（官方源可信）与置信度加权
        gap.confidence = max(gap.confidence, result.confidence)
        if observation.status == ObservationStatus.OK and result.confidence >= CLOSED_CONFIDENCE:
            gap.status = GapStatus.CONFIRMED
        elif gap.confidence > 0:
            gap.status = GapStatus.PARTIAL


__all__ = ["GapExecutor", "fetch_candidate"]
