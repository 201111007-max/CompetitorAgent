"""SubAgent — 子代理（M3 3.6 并行执行单元）

封装单缺口闭环：一个子代理负责一个 InfoGap 的采集+分析。
可与 ParallelRunner 配合并发执行多个独立缺口。
闭环核心逻辑委托 GapExecutor（问题 12.1 消重），与单 Agent 主路径（TacticalLoop）
行为完全一致。
"""

from __future__ import annotations

from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.core.budget import IterationBudget
from competitor_agent.core.gap_executor import GapExecutor
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.domain_types.strategy import CompetitorStrategy
from competitor_agent.interfaces.collector import ICompetitorDataSource
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
        self._executor = GapExecutor(
            selector=selector,
            extractor=extractor,
            analyzer=analyzer,
            budget=budget,
        )

    @property
    def field(self) -> str:
        return self._gap.field

    @property
    def gap(self) -> InfoGap:
        return self._gap

    def run(self) -> DimensionResult | None:
        """执行单缺口闭环，返回维度结论（失败返回 None）。"""
        return self._executor.execute(self._gap, self._strategy.competitor)
