"""SentimentAnalyzer — 社区口碑维度分析器（设计文档 24）

从社区源（HN/Reddit/X/YouTube，经设计文档 23 的 CommunitySourceProvider）聚合：
- signals：正/负/中信号（可追溯）
- positives / negatives：高频好评/吐槽点（各 ≤5，带证据）
- polarity_ratio：{pos, neg, neu} 占比
- verdict：一句话口碑结论

信号不足时返回低置信 [PARTIAL]，禁止编造。
"""
from __future__ import annotations

import json
from typing import Any

from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted
from competitor_agent.domain_types.enums import DimensionType
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation

_POSITIVE_MARKERS = ("好用", "好评", "推荐", "喜欢", "great", "awesome", "love", "fast", "recommend", "best")
_NEGATIVE_MARKERS = ("难用", "差评", "吐槽", "失望", "bug", "slow", "bad", "terrible", "crash", "worse", "贵", "限制")

_LOW_SIGNAL_VERDICT = "社区信号不足，无法形成可靠口碑结论（不编造）"


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

    def _parse_result(self, text: str) -> dict[str, Any]:
        return json.loads(text)  # type: ignore[no-any-return]

    def _rule_extract(self, observation: Observation) -> dict[str, Any]:
        text = observation.raw_text or ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        low_lines = [ln.lower() for ln in lines]

        signals: list[dict[str, str]] = []
        positives: list[str] = []
        negatives: list[str] = []

        for idx, low in enumerate(low_lines):
            if len(lines[idx]) > 200:
                continue
            has_pos = any(m in low for m in _POSITIVE_MARKERS)
            has_neg = any(m in low for m in _NEGATIVE_MARKERS)
            if not (has_pos or has_neg):
                continue
            polarity = "neu"
            if has_pos and not has_neg:
                polarity = "pos"
            elif has_neg and not has_pos:
                polarity = "neg"
            signals.append(
                {
                    "polarity": polarity,
                    "quote": lines[idx][:120],
                    "source_url": observation.evidence.url,
                }
            )
            if polarity == "pos":
                positives.append(lines[idx][:80])
            elif polarity == "neg":
                negatives.append(lines[idx][:80])

        pos_c, neg_c, neu_c = _count_polarity(signals)
        total = pos_c + neg_c + neu_c
        if total:
            ratio = {
                "pos": round(pos_c / total, 2),
                "neg": round(neg_c / total, 2),
                "neu": round(neu_c / total, 2),
            }
            verdict = f"社区口碑以{'正面' if pos_c >= neg_c else '负面'}为主（{pos_c}正/{neg_c}负/{neu_c}中）"
            confidence = 0.6 if total >= 3 else 0.5
        else:
            ratio = {"pos": 0.0, "neg": 0.0, "neu": 0.0}
            verdict = _LOW_SIGNAL_VERDICT
            confidence = 0.1

        return {
            "summary": verdict,
            "details": {
                "signals": signals[:20],
                "positives": _dedupe(positives)[:5],
                "negatives": _dedupe(negatives)[:5],
                "polarity_ratio": ratio,
                "verdict": verdict,
            },
            "confidence": confidence,
        }


def _count_polarity(signals: list[dict[str, str]]) -> tuple[int, int, int]:
    pos = sum(1 for s in signals if s.get("polarity") == "pos")
    neg = sum(1 for s in signals if s.get("polarity") == "neg")
    neu = sum(1 for s in signals if s.get("polarity") == "neu")
    return pos, neg, neu


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
