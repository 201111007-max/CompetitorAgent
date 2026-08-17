"""RoadmapAnalyzer — 路线图/roadmap 维度分析器（设计文档 47）

roadmap 是规划枚举内的合法维度（DIMENSION_PRIORITY 含 roadmap），
此前由 FallbackAnalyzer 兜底；设计文档 47 删除规则降级后，改为
独立 LLM 分析器（与其余 5 维同构），未注册维度一律抛 ValueError。

从 GitHub Releases / 官方文档 / changelog 提取版本节奏与计划内路线：
- releases：近期发布（版本号/日期/要点）
- upcoming：计划中/预告功能（roadmap 条目）
- 数据不足 → 低置信 [PARTIAL]，不编造。
"""
from __future__ import annotations

from typing import Any

from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted
from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.domain_types.enums import DimensionType
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation


class RoadmapAnalyzer(BaseCompetitorAnalyzer):
    """从 GitHub Releases / 文档 / changelog 盘点版本与路线"""

    dimension = DimensionType.ROADMAP

    def _build_prompt(self, observation: Observation, gap: InfoGap) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "你是竞品路线图分析师。从给定文本（GitHub Releases/官方文档/changelog）"
                    "提取版本发布与计划中功能，"
                    "输出 JSON: {\"summary\": 一句话总结, "
                    "\"details\": {\"releases\": [{\"version\": ..., \"date\": ..., "
                    "\"notes\": ...}], \"upcoming\": [\"计划功能1\", ...]}, "
                    "\"confidence\": 0-1}。没有明确路线数据的字段给空列表，不要编造具体版本或日期。"
                ),
            },
            {"role": "user", "content": wrap_untrusted(observation.raw_text[:4000], observation.evidence.url)},
        ]

    def _details_properties(self) -> dict[str, Any]:
        """details 结构：releases（版本节奏）+ upcoming（计划路线）。"""
        return {
            "releases": {"type": "array", "items": {"type": "object"}},
            "upcoming": {"type": "array", "items": {"type": "string"}},
        }
