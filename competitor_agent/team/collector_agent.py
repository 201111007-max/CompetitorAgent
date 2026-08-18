"""CollectorAgent — 采集 Agent

职责：接收 CompetitorStrategy，对每个缺口按 SourceSelector 降级链
采集数据，产出 Observation 列表，发布到 T_COLLECTED。
通过 ICompetitorDataSource 完成实际抓取（可注入 fake 测试）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.core.checkpoint import is_cancelled
from competitor_agent.core.gap_executor import fetch_candidate
from competitor_agent.core.source_dedup import SourceDedup
from competitor_agent.domain_types.enums import ObservationStatus
from competitor_agent.domain_types.observation import Observation
from competitor_agent.domain_types.strategy import CompetitorStrategy
from competitor_agent.interfaces.collector import ICompetitorDataSource
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.team.base_agent import AgentContext, AgentResult, AgentStatus, BaseAgent
from competitor_agent.team.message_bus import Envelope, T_COLLECTED, MessageBus

logger = logging.getLogger("competitor_agent.team.collector_agent")


class CollectorAgent(BaseAgent):
    """采集 Agent：缺口 → 候选源降级 → Observation 列表"""

    def __init__(
        self,
        bus: MessageBus,
        selector: SourceSelector,
        extractor: ICompetitorDataSource,
        memory: IFourLayerMemory | None = None,
        ingester: Any | None = None,
        session_id: str | None = None,
        providers: dict[str, object] | None = None,
        dedup: SourceDedup | None = None,  # 跨竞品同源去重（设计文档 49 §3.4），None → 原行为
    ) -> None:
        super().__init__("collector", bus, memory)
        self._selector = selector
        self._extractor = extractor
        self._ingester = ingester
        self._session_id = session_id or ""
        self._providers = dict(providers or {})
        self._dedup = dedup

    def run(self, ctx: AgentContext) -> AgentResult:
        """决策入口：采集缺口数据，产出 Observation 列表。"""
        try:
            observations = self.collect(ctx.strategy)
        except DataSourceUnavailableError as exc:
            return self._retry(ctx, exc)
        if not observations:
            return AgentResult(
                status=AgentStatus.DEGRADED,
                payload=[],
                reason="所有候选源均不可用，无观测数据",
            )
        return AgentResult(status=AgentStatus.SUCCESS, payload=observations)

    def collect(self, strategy: CompetitorStrategy) -> list[Observation]:
        """对每个缺口采集，返回观测列表（发布到总线）。"""
        observations: list[Observation] = []
        for gap in strategy.gaps:
            if self._session_id and is_cancelled(self._session_id):
                logger.info("会话 %s 已取消，停止采集 %s", self._session_id, gap.field)
                break
            for candidate in self._selector.candidates(gap, strategy.competitor):
                try:
                    obs = self._fetch(gap, candidate, strategy)
                except DataSourceUnavailableError as exc:
                    gap.record_source_try(candidate.source_name)
                    logger.info("候选源失败 %s: %s", candidate.source_name, exc)
                    continue
                gap.record_source_try(candidate.source_name)
                if obs.status in (ObservationStatus.OK, ObservationStatus.DEGRADED):
                    observations.append(obs)
                    self._ingest_observation(obs, strategy.competitor.name, gap.field)
                    break  # 该缺口已有可分析内容，停止降级
        self._bus.publish(T_COLLECTED, {"competitor": strategy.competitor.name, "observations": observations})
        return observations

    def _fetch(
        self,
        gap: InfoGap,
        candidate: Any,
        strategy: CompetitorStrategy,
    ) -> Observation:
        """抓取候选源；装配 SourceDedup 时经其缓存（同 URL / 同 content_hash 复用，设计文档 49 §3.4）。"""
        def _do_fetch() -> Observation:
            return fetch_candidate(
                gap, candidate, strategy.competitor, self._extractor, providers=self._providers
            )

        if self._dedup is None or not candidate.url:
            return _do_fetch()
        return self._dedup.get_or_fetch(candidate.url, _do_fetch)

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

    async def _handle_async(self, env: Envelope) -> dict[str, Any] | None:
        """异步订阅者（设计文档 33 §3.1）：响应采集请求并返回观测列表。"""
        strategy = env.payload.get("strategy")
        if strategy is None:
            return None
        try:
            observations = await asyncio.to_thread(self.collect, strategy)
        except Exception as exc:  # noqa: BLE001 —— 采集失败降级，不阻塞流水线
            logger.warning("异步采集失败: %s", exc)
            return None
        return {
            "competitor": strategy.competitor.name,
            "observations": observations,
            "sources_tried": [g.sources_tried for g in strategy.gaps],
        }

    def process(self, strategy: CompetitorStrategy) -> list[Observation]:
        """总线驱动入口（供 Orchestrator 调用）"""
        return self.collect(strategy)
