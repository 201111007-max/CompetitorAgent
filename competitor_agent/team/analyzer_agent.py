"""AnalyzerAgent — 分析 Agent

职责：将 Observation 按维度交给对应分析器，产出 DimensionResult，
发布到 T_ANALYZED。
"""
from __future__ import annotations

import logging

from competitor_agent.analyzers.registry import AnalyzerRegistry
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.interfaces.context import AnalysisContext
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.team.base_agent import AgentContext, AgentResult, AgentStatus, BaseAgent
from competitor_agent.team.message_bus import T_ANALYZED, MessageBus

logger = logging.getLogger("competitor_agent.team.analyzer_agent")


class AnalyzerAgent(BaseAgent):
    """分析 Agent：观测 → 维度结论"""

    def __init__(
        self,
        bus: MessageBus,
        registry: AnalyzerRegistry,
        memory: IFourLayerMemory | None = None,
    ) -> None:
        super().__init__("analyzer", bus, memory)
        self._registry = registry

    def run(self, ctx: AgentContext) -> AgentResult:
        """决策入口：分析观测，产出维度结论。"""
        observations: list[Observation] = ctx.extra.get("observations", [])
        if not observations:
            return AgentResult(
                status=AgentStatus.DEGRADED,
                payload=[],
                reason="无观测数据可分析",
            )
        try:
            results = self.analyze(ctx.strategy.competitor.name, observations)
        except Exception as exc:  # noqa: BLE001 — 分析失败统一走重试/降级
            return self._retry(ctx, exc)
        if not results:
            return AgentResult(
                status=AgentStatus.DEGRADED,
                payload=[],
                reason="观测数据未产出任何维度结论",
            )
        return AgentResult(status=AgentStatus.SUCCESS, payload=results)

    def analyze(self, competitor_name: str, observations: list[Observation]) -> list[DimensionResult]:
        results: list[DimensionResult] = []
        for obs in observations:
            analyzer = self._registry.get(obs.gap_field)
            result = analyzer.analyze(
                obs,
                InfoGap(field=obs.gap_field),
                AnalysisContext(competitor_name=competitor_name, dimension=analyzer.dimension),
            )
            results.append(result)
        self._bus.publish(T_ANALYZED, {"competitor": competitor_name, "results": results})
        return results
