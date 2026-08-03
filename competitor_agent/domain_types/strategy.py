"""分析策略定义"""
from __future__ import annotations

from dataclasses import dataclass, field

from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import DimensionType
from competitor_agent.domain_types.info_gap import InfoGap


@dataclass
class DimensionBudget:
    """单维度迭代预算分配"""

    dimension: DimensionType
    max_iterations: int = 3


@dataclass
class CompetitorStrategy:
    """竞争对手分析策略：缺口清单 + 预算 + 终止阈值"""

    competitor: Competitor
    gaps: list[InfoGap] = field(default_factory=list)
    budget_allocation: dict[DimensionType, int] = field(default_factory=dict)
    terminal_thresholds: dict[str, float] = field(default_factory=lambda: {"confidence": 0.8})