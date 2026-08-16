"""AnalyzerRegistry — 维度 → 分析器映射"""
from __future__ import annotations

from typing import Any

from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.analyzers.ecosystem_analyzer import EcosystemAnalyzer
from competitor_agent.analyzers.fallback_analyzer import FallbackAnalyzer
from competitor_agent.analyzers.feature_analyzer import FeatureAnalyzer
from competitor_agent.analyzers.performance_analyzer import PerformanceAnalyzer
from competitor_agent.analyzers.pricing_analyzer import PricingAnalyzer
from competitor_agent.analyzers.sentiment_analyzer import SentimentAnalyzer
from competitor_agent.llm.client import LLMClient


class AnalyzerRegistry:
    """根据维度字段返回对应分析器；未注册维度回退到 FallbackAnalyzer"""

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
        }

    def get(self, field: str) -> BaseCompetitorAnalyzer:
        return self._analyzers.get(
            field,
            FallbackAnalyzer(llm=self._llm, use_llm=self._use_llm, tool_dispatcher=self._tool_dispatcher),
        )