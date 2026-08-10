"""AnalyzerAgent — 分析 Agent

职责：将 Observation 按维度交给对应分析器，产出 DimensionResult，
发布到 T_ANALYZED。
"""
from __future__ import annotations

import logging
from typing import Any

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
        retriever: Any | None = None,
    ) -> None:
        super().__init__("analyzer", bus, memory)
        self._registry = registry
        self._retriever = retriever

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
                AnalysisContext(
                    competitor_name=competitor_name,
                    dimension=analyzer.dimension,
                    rag_context=self._retrieve_rag(competitor_name, obs.gap_field),
                ),
            )
            results.append(result)
        self._bus.publish(T_ANALYZED, {"competitor": competitor_name, "results": results})
        return results

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
