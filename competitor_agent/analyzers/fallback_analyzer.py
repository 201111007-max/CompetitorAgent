"""FallbackAnalyzer — LLM 不可用时的规则降级（不崩溃，仍产出报告）"""
from __future__ import annotations

from typing import Any

from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.domain_types.enums import DimensionType
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.interfaces.context import AnalysisContext


class FallbackAnalyzer(BaseCompetitorAnalyzer):
    """兜底分析器：任意维度都返回文本摘要（置信度低）"""

    dimension = DimensionType.FEATURE

    def _analyze_with_rules(
        self,
        observation: Observation,
        gap: InfoGap,
        context: AnalysisContext,
    ) -> DimensionResult:
        return self._make_result(
            observation,
            gap,
            self._rule_extract(observation),
            confidence=0.3,
        )

    def _rule_extract(self, observation: Observation) -> dict[str, Any]:
        text = observation.raw_text.strip()
        return {
            "summary": text[:300],
            "details": {"source_status": observation.status.value},
        }