"""StrategicLoop — 战略循环：任务 → 信息缺口清单 + 预算分配

规则版（M1 无 LLM）：
1. 解析任务识别竞品（注册表 + 规则）
2. 生成 InfoGap 清单（按维度默认优先级 + 初始置信度 0）
3. 按 config 分配维度预算
4. 产出 CompetitorStrategy

LLM 版规划（可选增强）在 M2 记忆接入时替换 plan() 内部。
"""
from __future__ import annotations

import logging

from competitor_agent.core.competitor_registry import resolve_competitor
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import DimensionType, GapStatus
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.strategy import CompetitorStrategy
from competitor_agent.interfaces.context import Skill
from competitor_agent.interfaces.memory import IFourLayerMemory

logger = logging.getLogger("competitor_agent.core.strategic_loop")

# 维度 → 默认优先级（对应 config dimensions.default_budget 的配比）
DIMENSION_PRIORITY: dict[str, int] = {
    "pricing": 9,
    "feature": 8,
    "performance": 7,
    "ecosystem": 6,
    "sentiment": 5,
    "roadmap": 4,
}

# 用户任务里声明"要重点看 X"时给该维度提权
_FOCUS_KEYWORDS = {
    "pricing": ["定价", "价格", "多少钱", "pricing", "price", "plan"],
    "performance": ["性能", "benchmark", "swe-bench", "speed", "性能评测"],
    "features": ["功能", "特性", "features", "feature"],
}


class StrategicPlanner:
    """规则版战略规划器"""

    def __init__(
        self,
        enabled_dimensions: list[str] | None = None,
        default_budget: dict[str, int] | None = None,
    ) -> None:
        self._enabled = enabled_dimensions or list(DIMENSION_PRIORITY.keys())
        self._budget = default_budget or {
            "feature": 3,
            "pricing": 2,
            "performance": 3,
            "ecosystem": 2,
            "sentiment": 2,
            "roadmap": 1,
        }

    def plan(self, task: str, memory: IFourLayerMemory | None = None) -> CompetitorStrategy:
        """解析任务 → 竞品 + 缺口清单 + 预算"""
        competitor = resolve_competitor(task)
        gaps = self._build_gaps(task)
        self._apply_memory_boost(gaps, competitor, memory)
        budget = self._allocate_budget()
        return CompetitorStrategy(
            competitor=competitor,
            gaps=gaps,
            budget_allocation={
                DimensionType(dim): n for dim, n in budget.items() if dim in self._enabled
            },
            terminal_thresholds={"confidence": 0.8},
        )

    def _build_gaps(self, task: str) -> list[InfoGap]:
        """按维度生成缺口清单，结合任务关键词提权"""
        lowered = task.lower()
        gaps: list[InfoGap] = []
        for dim in self._enabled:
            priority = DIMENSION_PRIORITY[dim]
            for keyword_dim, keywords in _FOCUS_KEYWORDS.items():
                if keyword_dim == dim and any(k in lowered for k in keywords):
                    priority = min(priority + 2, 10)
                    break
            gaps.append(InfoGap(field=dim, priority=priority, confidence=0.0, status=GapStatus.OPEN))
        return gaps

    def _apply_memory_boost(
        self,
        gaps: list[InfoGap],
        competitor: Competitor,
        memory: IFourLayerMemory | None,
    ) -> None:
        """记忆提升：历史技能命中的缺口初始置信度提升"""
        if memory is None:
            return
        try:
            skills: list[Skill] = memory.retrieve_skills(competitor.name)
        except Exception:  # 记忆层损坏不影响规划
            logger.warning("记忆取回失败，跳过 memory boost", exc_info=True)
            return
        for gap in gaps:
            for skill in skills:
                if skill.gap_field == gap.field and skill.success:
                    gap.confidence = min(gap.confidence + 0.2, 0.8)
                    break

    def _allocate_budget(self) -> dict[str, int]:
        return {dim: self._budget.get(dim, 1) for dim in self._enabled}