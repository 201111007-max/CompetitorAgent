"""CollectorAgent — 采集 Agent

职责：接收 CompetitorStrategy，对每个缺口按 SourceSelector 降级链
采集数据，产出 Observation 列表，发布到 T_COLLECTED。
通过 ICompetitorDataSource 完成实际抓取（可注入 fake 测试）。
"""
from __future__ import annotations

import logging

from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.domain_types.enums import ObservationStatus
from competitor_agent.domain_types.observation import Observation
from competitor_agent.domain_types.strategy import CompetitorStrategy
from competitor_agent.interfaces.collector import ICompetitorDataSource
from competitor_agent.interfaces.context import SourceContext
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError
from competitor_agent.team.message_bus import T_COLLECTED, MessageBus

logger = logging.getLogger("competitor_agent.team.collector_agent")


class CollectorAgent:
    """采集 Agent：缺口 → 候选源降级 → Observation 列表"""

    def __init__(
        self,
        bus: MessageBus,
        selector: SourceSelector,
        extractor: ICompetitorDataSource,
    ) -> None:
        self._bus = bus
        self._selector = selector
        self._extractor = extractor

    def collect(self, strategy: CompetitorStrategy) -> list[Observation]:
        """对每个缺口采集，返回观测列表（发布到总线）。"""
        observations: list[Observation] = []
        for gap in strategy.gaps:
            for candidate in self._selector.candidates(gap, strategy.competitor):
                try:
                    obs = self._extractor.fetch(
                        gap,
                        SourceContext(
                            competitor_name=strategy.competitor.name,
                            query=gap.field,
                            kwargs={"url": candidate.url},
                        ),
                    )
                except DataSourceUnavailableError as exc:
                    gap.record_source_try(candidate.source_name)
                    logger.info("候选源失败 %s: %s", candidate.source_name, exc)
                    continue
                gap.record_source_try(candidate.source_name)
                if obs.status in (ObservationStatus.OK, ObservationStatus.DEGRADED):
                    observations.append(obs)
                    break  # 该缺口已有可分析内容，停止降级
        self._bus.publish(T_COLLECTED, {"competitor": strategy.competitor.name, "observations": observations})
        return observations

    def process(self, strategy: CompetitorStrategy) -> list[Observation]:
        """总线驱动入口（供 Orchestrator 调用）"""
        return self.collect(strategy)