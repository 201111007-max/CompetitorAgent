"""AnalyzerRegistry — 维度 → 分析器映射（设计文档 47：未注册维度抛 ValueError）"""
from __future__ import annotations

from typing import Any

from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.analyzers.ecosystem_analyzer import EcosystemAnalyzer
from competitor_agent.analyzers.feature_analyzer import FeatureAnalyzer
from competitor_agent.analyzers.performance_analyzer import PerformanceAnalyzer
from competitor_agent.analyzers.pricing_analyzer import PricingAnalyzer
from competitor_agent.analyzers.roadmap_analyzer import RoadmapAnalyzer
from competitor_agent.analyzers.sentiment_analyzer import SentimentAnalyzer
from competitor_agent.llm.client import LLMClient


class AnalyzerRegistry:
    """根据维度字段返回对应分析器；未注册维度抛 ValueError（LLM 时代维度由规划枚举约束）"""

    def __init__(
        self,
        llm: LLMClient | None = None,
        use_llm: bool = True,
        tool_dispatcher: Any | None = None,
    ) -> None:
        self._llm = llm
        self._use_llm = use_llm
        self._tool_dispatcher = tool_dispatcher  # 设计文档 44：链式分析工具补证分发器
        self._analyzers = {
            "pricing": PricingAnalyzer(llm=llm, use_llm=use_llm, tool_dispatcher=tool_dispatcher),
            "feature": FeatureAnalyzer(llm=llm, use_llm=use_llm, tool_dispatcher=tool_dispatcher),
            "performance": PerformanceAnalyzer(llm=llm, use_llm=use_llm, tool_dispatcher=tool_dispatcher),
            "ecosystem": EcosystemAnalyzer(llm=llm, use_llm=use_llm, tool_dispatcher=tool_dispatcher),
            "sentiment": SentimentAnalyzer(llm=llm, use_llm=use_llm, tool_dispatcher=tool_dispatcher),
            "roadmap": RoadmapAnalyzer(llm=llm, use_llm=use_llm, tool_dispatcher=tool_dispatcher),
        }

    def get(self, field: str) -> BaseCompetitorAnalyzer:
        analyzer = self._analyzers.get(field)
        if analyzer is None:
            raise ValueError(f"未注册的分析维度: {field!r}（LLM 时代维度由规划枚举约束）")
        return analyzer
