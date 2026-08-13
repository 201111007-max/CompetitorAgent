"""AnalyzerRegistry — 维度 → 分析器映射"""
from __future__ import annotations

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

    def __init__(self, llm: LLMClient | None = None, use_llm: bool = True) -> None:
        self._llm = llm
        self._use_llm = use_llm
        self._analyzers = {
            "pricing": PricingAnalyzer(llm=llm, use_llm=use_llm),
            "feature": FeatureAnalyzer(llm=llm, use_llm=use_llm),
            "performance": PerformanceAnalyzer(llm=llm, use_llm=use_llm),
            "ecosystem": EcosystemAnalyzer(llm=llm, use_llm=use_llm),
            "sentiment": SentimentAnalyzer(llm=llm, use_llm=use_llm),
        }

    def get(self, field: str) -> BaseCompetitorAnalyzer:
        return self._analyzers.get(field, FallbackAnalyzer(llm=self._llm, use_llm=self._use_llm))