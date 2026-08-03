"""PerformanceAnalyzer — 性能评测维度分析器"""
from __future__ import annotations

import json
import re
from typing import Any

from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.domain_types.enums import DimensionType
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation

_BENCHMARK_MARKERS = re.compile(
    r"(swe-bench|aider|human-eval|percent|score|accuracy|pass@|win rate)", re.IGNORECASE
)


class PerformanceAnalyzer(BaseCompetitorAnalyzer):
    """从评测页/榜单提取性能指标"""

    dimension = DimensionType.PERFORMANCE

    def _build_prompt(self, observation: Observation, gap: InfoGap) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "你是竞品性能分析师。从文本提取基准测试数据，"
                    "输出 JSON: {\"summary\": 一句话总结, "
                    "\"details\": {\"benchmarks\": [{\"name\": ..., \"score\": ...}]}, "
                    "\"confidence\": 0-1}"
                ),
            },
            {"role": "user", "content": observation.raw_text[:4000]},
        ]

    def _parse_result(self, text: str) -> dict[str, Any]:
        return json.loads(text)

    def _rule_extract(self, observation: Observation) -> dict[str, Any]:
        benchmarks = []
        for line in observation.raw_text.splitlines():
            if _BENCHMARK_MARKERS.search(line) and len(line) < 200:
                benchmarks.append({"raw": line.strip()})
        return {
            "summary": f"检测到 {len(benchmarks)} 条性能相关记录",
            "details": {"benchmarks": benchmarks[:10]},
        }