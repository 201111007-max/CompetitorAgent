"""TacticalLoop — 单缺口闭环：预算→选源→采集→分析→置信度更新

流程（对照架构文档 5.2）：
1. budget.consume()
2. SourceSelector 给候选源（降级链）
3. collector.fetch → Observation
4. analyzer.analyze → 更新缺口置信度 + 证据
5. 多源一致/置信达标 → CONFIRMED/CLOSED；失败 → 记录并换降级源

实现：闭环核心逻辑已收敛到 GapExecutor（问题 12.1 消重），本类保留公共接口并委托之。
"""

from __future__ import annotations

from typing import Any

from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.collector.web_extractor import WebExtractor
from competitor_agent.core.budget import IterationBudget
from competitor_agent.core.gap_executor import GapExecutor
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.domain_types.strategy import CompetitorStrategy
from competitor_agent.interfaces.collector import ICompetitorDataSource
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
        session_id: str | None = None,
        providers: dict[str, object] | None = None,
    ) -> None:
        self._executor = GapExecutor(
            selector=selector,
            extractor=extractor,
            analyzer=analyzer,
            budget=budget,
            extractors=extractors,
            ingester=ingester,
            retriever=retriever,
            session_id=session_id,
            providers=providers,
        )

    @property
    def executor(self) -> GapExecutor:
        return self._executor

    def execute(self, gap: InfoGap, strategy: CompetitorStrategy) -> DimensionResult | None:
        """执行单缺口闭环。返回维度结论（失败/被取消返回 None）。"""
        return self._executor.execute(gap, strategy.competitor)
