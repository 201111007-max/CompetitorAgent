"""PerformanceAnalyzer — 性能评测维度分析器（设计文档 25 / 47）

优先级：榜单证据（context.benchmark_scores，权威直连）> 官网/文档页数字。
同指标冲突以榜单为准并在报告注明来源；仅有页面 → 置信度降档；
均无 → [PARTIAL] 注明"无权威榜单数据"，不编造。
设计文档 47：仅 LLM 分析（无规则降级）。
"""
from __future__ import annotations

from typing import Any

from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted
from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.domain_types.enums import DimensionType, ResultStatus
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.interfaces.context import AnalysisContext

# 页面条目名 → 榜单指标的关键字映射（用于"同指标以榜单为准"）
_BOARD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "swe_bench_verified": ("swe-bench",),
    "aider_polyglot": ("aider",),
    "terminal_bench": ("terminal-bench", "terminal bench"),
    "lm_arena": ("lmarena", "lm arena"),
}


class PerformanceAnalyzer(BaseCompetitorAnalyzer):
    """从评测页/榜单提取性能指标；榜单优先，页面兜底"""

    dimension = DimensionType.PERFORMANCE

    def analyze(
        self,
        observation: Observation,
        gap: InfoGap,
        context: AnalysisContext,
    ) -> DimensionResult:
        result = super().analyze(observation, gap, context)
        board_scores = getattr(context, "benchmark_scores", None) or {}
        base_benchmarks = result.details.get("benchmarks", [])
        merged = _merge_benchmarks(board_scores, base_benchmarks)

        if board_scores:
            summary = f"榜单直连 {len(board_scores)} 项基准（页面兜底 {len(base_benchmarks)} 条）"
            confidence = 0.85
            status = ResultStatus.COMPLETE
        elif base_benchmarks:
            summary = result.summary
            confidence = min(result.confidence, 0.6)  # 无权威榜单 → 降档
            status = ResultStatus.COMPLETE if confidence >= 0.5 else ResultStatus.PARTIAL
        else:
            summary = "无权威榜单数据，未编造性能数字"
            confidence = 0.3
            status = ResultStatus.PARTIAL

        return DimensionResult(
            dimension=self.dimension.value,
            summary=summary,
            details={**result.details, "benchmarks": merged, "board_priority": bool(board_scores)},
            confidence=confidence,
            evidence=result.evidence,
            status=status,
        )

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
            {"role": "user", "content": wrap_untrusted(observation.raw_text[:4000], observation.evidence.url)},
        ]

    def _details_properties(self) -> dict[str, Any]:
        """details 结构（设计文档 34）：benchmarks 与评测 _benchmark_score 抽取键对齐。

        元素仅约束 object——兼容 LLM 的 name/score 契约键与 mock 的 raw 行形态。
        """
        return {"benchmarks": {"type": "array", "items": {"type": "object"}}}


def _merge_benchmarks(board_scores: dict[str, Any], base_benchmarks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """榜单优先合并：无榜单 → 原样保留页面/LLM 结果（不破坏评测契约）；
    有榜单 → 榜单条目置前，同指标（关键字匹配）的页面条目让位。"""
    if not board_scores:
        return base_benchmarks
    merged = [
        {
            "name": s.board_label,
            "board": board,
            "score": s.score,
            "unit": s.unit,
            "source": "leaderboard",
            "source_url": s.source_url,
            "retrieved_at": s.retrieved_at,
        }
        for board, s in board_scores.items()
    ]
    for entry in base_benchmarks:
        name = str(entry.get("name") or "") + " " + str(entry.get("raw") or "")
        if _match_board(name, board_scores) is not None:
            continue  # 同指标已在榜单，页面数字让位
        merged.append(entry)
    return merged


def _match_board(name: str, board_scores: dict[str, Any]) -> str | None:
    low = name.lower()
    for board, keys in _BOARD_KEYWORDS.items():
        if board in board_scores and any(k in low for k in keys):
            return board
    return None
