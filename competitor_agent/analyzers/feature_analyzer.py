"""FeatureAnalyzer — 功能矩阵维度分析器"""
from __future__ import annotations

import json
from typing import Any

from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.domain_types.enums import DimensionType
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation

_FEATURE_MARKERS = (
    "support", "integration", "cli", "agent", "terminal", "multimodal",
    "rag", "mcp", "code", "review", "deploy", "token",
)


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
            {"role": "user", "content": observation.raw_text[:4000]},
        ]

    def _parse_result(self, text: str) -> dict[str, Any]:
        return json.loads(text)

    def _rule_extract(self, observation: Observation) -> dict[str, Any]:
        features = []
        for line in observation.raw_text.splitlines():
            low = line.lower()
            if any(m in low for m in _FEATURE_MARKERS) and len(line) < 200:
                candidate = line.strip()
                if candidate and candidate not in features:
                    features.append(candidate)
        return {
            "summary": f"检测到 {len(features)} 个功能相关描述",
            "details": {"features": features[:15]},
        }