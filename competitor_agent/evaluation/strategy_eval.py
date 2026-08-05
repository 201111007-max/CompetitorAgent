"""StrategyEval — 工具选择准确率 / 成本效率评测（3.4）

评估 Agent 的决策质量：
- tool_selection_accuracy = 正确选源/总决策（对每个缺口，Agent 选的源
  是否与"最优源"一致）
- cost_efficiency = 报告价值 / 总成本（成本越低、结论越完整越高效）
- source_rank_ratio = 命中最优源所需的降级尝试次数占比（1=第一候选命中）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StrategyCase:
    """单条策略评测用例"""
    task: str
    chosen_sources: list[str]  # Agent 实际选择的源（按尝试顺序）
    best_source: str  # 标注的最优源
    total_cost: float = 0.0
    outcome_complete: bool = True  # 结论是否完整（价值）
    depth: int = 0  # 实际降级深度（尝试了几个源）
    case_id: str = ""
    tags: list[str] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class StrategyMetrics:
    tool_selection_accuracy: float = 0.0
    cost_efficiency: float = 0.0
    avg_source_rank: float = 0.0  # 平均命中排名（1=首候选命中）
    per_case: list[dict[str, Any]] = field(default_factory=list)


class StrategyEvaluator:
    """计算工具选择准确率与成本效率"""

    def evaluate(self, cases: list[StrategyCase]) -> StrategyMetrics:
        if not cases:
            return StrategyMetrics()

        acc: list[float] = []
        ranks: list[float] = []
        efficiencies: list[float] = []
        per_case: list[dict[str, Any]] = []

        for case in cases:
            hit = case.best_source in case.chosen_sources
            acc.append(1.0 if hit else 0.0)
            # 命中排名：最优源在 chosen_sources 的位置（1-based）；未命中取 worst
            rank = case.chosen_sources.index(case.best_source) + 1 if hit else len(case.chosen_sources) + 1
            ranks.append(float(rank))
            # 成本效率 = 价值 / 成本；价值 = 结论完整度（0~1）× 命中（1/0.3）
            value = (1.0 if case.outcome_complete else 0.4) * (1.0 if hit else 0.3)
            cost = case.total_cost if case.total_cost > 0 else 1e-6
            efficiencies.append(value / cost)
            per_case.append(
                {
                    "task": case.task,
                    "hit": hit,
                    "rank": rank,
                    "cost": case.total_cost,
                    "efficiency": value / cost,
                }
            )

        return StrategyMetrics(
            tool_selection_accuracy=round(sum(acc) / len(acc), 4),
            cost_efficiency=round(sum(efficiencies) / len(efficiencies), 4),
            avg_source_rank=round(sum(ranks) / len(ranks), 4),
            per_case=per_case,
        )


__all__ = ["StrategyCase", "StrategyEvaluator", "StrategyMetrics"]