"""AnalyzerAgent — 分析 Agent

职责：将 Observation 按维度交给对应分析器，产出 DimensionResult，
发布到 T_ANALYZED。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from competitor_agent.analyzers.base import analyze_with_context, retrieve_rag_text
from competitor_agent.analyzers.registry import AnalyzerRegistry
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.team.base_agent import AgentContext, AgentResult, AgentStatus, BaseAgent
from competitor_agent.team.message_bus import T_ANALYZED, Envelope, MessageBus

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
            results.append(self.analyze_observation(competitor_name, obs))
        self._bus.publish(T_ANALYZED, {"competitor": competitor_name, "results": results})
        return results

    def analyze_observation(
        self, competitor_name: str, obs: Observation
    ) -> DimensionResult:
        """单缺口分析（供串行循环与异步并行编排复用，无总线副作用）

        统一分析段（设计文档 46 §3.1）：与 single 路径 GapExecutor 同一实现
        （RAG/记忆注入 + 校验 + 补全），消除两套分析实现漂移。
        """
        analyzer = self._registry.get(obs.gap_field)
        return analyze_with_context(
            analyzer,
            obs,
            InfoGap(field=obs.gap_field),
            competitor_name=competitor_name,
            rag_context=retrieve_rag_text(self._retriever, competitor_name, obs.gap_field),
            memory_context=self._retrieve_memory(competitor_name, obs.gap_field),
        )

    async def _handle_async(self, env: Envelope) -> DimensionResult | None:
        """异步订阅者（设计文档 33 §3.1）：处理单观测分析请求并返回结论。

        to_thread 让同步分析在线程池中真正并行，事件循环不被阻塞。
        """
        payload = env.payload
        obs = payload.get("observation")
        if obs is None:
            return None
        try:
            return await asyncio.to_thread(
                self.analyze_observation, payload.get("competitor", ""), obs
            )
        except Exception as exc:  # noqa: BLE001 —— 单缺口分析失败降级，不阻塞流水线
            logger.warning("异步分析失败: %s: %s", obs.gap_field, exc)
            return None

    def _retrieve_memory(self, competitor: str, dimension: str) -> str:
        """记忆召回（设计文档 45）：team 路径与 single 对齐——复用 recent_context 相关度召回。

        无记忆（memory=None）或召回失败均静默返回空串（enable_memory=False 全绿）。
        """
        if self._memory is None:
            return ""
        try:
            return "\n".join(
                self._memory.recent_context(competitor, top_k=3, query=dimension)
            )
        except Exception:  # noqa: BLE001 — 记忆召回失败不影响主流程
            logger.warning("记忆召回失败: %s/%s", competitor, dimension)
            return ""
