"""FeatureAnalyzer — 功能矩阵维度分析器（设计文档 47：仅 LLM，无规则降级）"""
from __future__ import annotations

from typing import Any

from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted
from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.domain_types.enums import DimensionType
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation


class FeatureAnalyzer(BaseCompetitorAnalyzer):
    """从文档/官网提取功能点清单"""

    dimension = DimensionType.FEATURE

    def _build_prompt(self, observation: Observation, gap: InfoGap) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "你是竞品功能分析师。从文本提取核心功能列表，"
                    "输出 JSON: {\"summary\": 一句话总结, "
                    "\"details\": {\"features\": [\"feature1\", ...]}, \"confidence\": 0-1}"
                ),
            },
            {"role": "user", "content": wrap_untrusted(observation.raw_text[:4000], observation.evidence.url)},
        ]

    def _details_properties(self) -> dict[str, Any]:
        return {"features": {"type": "array", "items": {"type": "string"}}}
