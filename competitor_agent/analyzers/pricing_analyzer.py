"""PricingAnalyzer — 定价/版本维度分析器"""
from __future__ import annotations

import json
import re
from typing import Any

from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.domain_types.enums import DimensionType
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation

_PRICE_PATTERN = re.compile(r"\$\s?(\d+(?:\.\d+)?)\s?(?:/|per\s)?(mo|month|user|seat)?", re.IGNORECASE)


class PricingAnalyzer(BaseCompetitorAnalyzer):
    """从定价页提取 plan 列表与价格"""

    dimension = DimensionType.PRICING

    def _build_prompt(self, observation: Observation, gap: InfoGap) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "你是竞品定价分析师。从给定网页文本中提取定价计划，"
                    "输出 JSON: {\"summary\": 一句话总结, "
                    "\"details\": {\"plans\": [{\"name\": ..., \"price\": ..., \"period\": ...}]}, "
                    "\"confidence\": 0-1}"
                ),
            },
            {"role": "user", "content": observation.raw_text[:4000]},
        ]

    def _parse_result(self, text: str) -> dict[str, Any]:
        return json.loads(text)

    def _rule_extract(self, observation: Observation) -> dict[str, Any]:
        plans = []
        for line in observation.raw_text.splitlines():
            match = _PRICE_PATTERN.search(line)
            if match and len(line) < 300:
                plans.append(
                    {
                        "name": line[:40].strip(),
                        "price": match.group(1),
                        "period": match.group(2) or "mo",
                    }
                )
        return {
            "summary": f"检测到 {len(plans)} 个定价条目",
            "details": {"plans": plans[:10]},
        }