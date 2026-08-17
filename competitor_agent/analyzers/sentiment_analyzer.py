"""SentimentAnalyzer — 社区口碑维度分析器（设计文档 24 / 47）

从社区源（HN/Reddit/X/YouTube，经设计文档 23 的 CommunitySourceProvider）聚合：
- signals：正/负/中信号（可追溯）
- positives / negatives：高频好评/吐槽点（各 ≤5，带证据）
- polarity_ratio：{pos, neg, neu} 占比
- verdict：一句话口碑结论

信号不足时返回低置信 [PARTIAL]，禁止编造。设计文档 47：仅 LLM 分析（无规则降级）。
"""
from __future__ import annotations

from typing import Any

from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted
from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.domain_types.enums import DimensionType
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation


class SentimentAnalyzer(BaseCompetitorAnalyzer):
    """从社区信号盘点口碑，空信号 → 低置信 [PARTIAL]"""

    dimension = DimensionType.SENTIMENT

    def _build_prompt(self, observation: Observation, gap: InfoGap) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "你是竞品社区口碑分析师。从给定社区文本（HN/Reddit/X/YouTube 等）提取口碑信号，"
                    "输出 JSON: {\"summary\": 一句话总结, "
                    "\"details\": {\"signals\": [{\"polarity\": \"pos|neg|neu\", "
                    "\"quote\": ..., \"source_url\": ...}], "
                    "\"positives\": [\"...\"], \"negatives\": [\"...\"], "
                    "\"polarity_ratio\": {\"pos\": 0-1, \"neg\": 0-1, \"neu\": 0-1}, "
                    "\"verdict\": 一句话口碑结论}, "
                    "\"confidence\": 0-1}。正/负要点各不超过 5 条并附证据来源；"
                    "信号不足时 verdict 注明\"信号不足\"且 confidence 接近 0，不要编造。"
                ),
            },
            {"role": "user", "content": wrap_untrusted(observation.raw_text[:4000], observation.evidence.url)},
        ]

    def _details_properties(self) -> dict[str, Any]:
        """details 结构（设计文档 34）：对齐评测 _sentiment_signal 抽取键命名空间。"""
        return {
            "signals": {"type": "array", "items": {"type": "object"}},
            "positives": {"type": "array", "items": {"type": "string"}},
            "negatives": {"type": "array", "items": {"type": "string"}},
            "polarity_ratio": {"type": "object"},
            "verdict": {"type": "string"},
        }
