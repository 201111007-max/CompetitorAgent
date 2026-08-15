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
from competitor_agent.core.task_parser import parse_task
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import DimensionType, GapStatus
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.strategy import CompetitorStrategy
from competitor_agent.interfaces.context import Skill
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.llm.client import LLMClient

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
        llm: LLMClient | None = None,
        use_llm: bool = True,
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
        self._llm = llm
        self._use_llm = use_llm

    def plan(self, task: str, memory: IFourLayerMemory | None = None) -> CompetitorStrategy:
        """解析任务 → 竞品 + 缺口清单 + 预算（内部先 parse_task，保持签名向后兼容）"""
        parsed = parse_task(task, llm=self._llm, use_llm=self._use_llm)
        competitor = self._resolve_with_sources(parsed)
        gaps = self._build_gaps(task, parsed.dimensions)
        self._apply_memory_boost(gaps, competitor, memory)
        self._apply_pattern_boost(gaps, competitor, memory)
        budget = self._allocate_budget(parsed.dimensions)
        return CompetitorStrategy(
            competitor=competitor,
            gaps=gaps,
            budget_allocation={
                DimensionType(dim): n for dim, n in budget.items() if dim in self._enabled
            },
            terminal_thresholds={"confidence": 0.8},
        )

    def _resolve_with_sources(self, parsed: object) -> Competitor:
        """解析竞品 + 注入自定义数据源（custom_sources → official_links，供 SourceSelector 使用）"""
        competitor = resolve_competitor(str(getattr(parsed, "primary_competitor", "")))
        custom = getattr(parsed, "custom_sources", {}) or {}
        if not custom:
            return competitor
        links = dict(competitor.official_links)
        links.update({k: v for k, v in custom.items() if v})
        return Competitor(
            name=competitor.name,
            aliases=competitor.aliases,
            category=competitor.category,
            official_links=links,
        )

    def _build_gaps(self, task: str, dimensions: list[str] | None = None) -> list[InfoGap]:
        """按维度生成缺口清单，结合任务关键词提权；dimensions 非空则只生成白名单内缺口"""
        lowered = task.lower()
        enabled = self._enabled if dimensions is None else [d for d in self._enabled if d in dimensions]
        gaps: list[InfoGap] = []
        for dim in enabled:
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

    def _apply_pattern_boost(
        self,
        gaps: list[InfoGap],
        competitor: Competitor,
        memory: IFourLayerMemory | None,
    ) -> None:
        """L4 进化模式消费（设计文档 45）：成功模式提权 / 失败反例降权。

        与 _apply_memory_boost（L3 技能）并列：按维度检索 (pattern, outcome)，
        成功 → 初始置信度 +0.1（封顶 0.9）；失败/降级 → 未定置信缺口降权（优先级 -1，下限 1）。
        只读消费不新增写入；读取失败静默降级（记忆层损坏不影响规划）。
        """
        if memory is None:
            return
        for gap in gaps:
            try:
                entries = memory.retrieve_patterns_with_outcome(competitor.name, gap.field)
            except Exception:  # 记忆层损坏不影响规划
                logger.warning("L4 模式取回失败，跳过 pattern boost: field=%s", gap.field, exc_info=True)
                continue
            for _pattern, outcome in entries:
                if outcome == "success":
                    gap.confidence = min(gap.confidence + 0.1, 0.9)
                elif outcome in ("failure", "degraded") and gap.confidence == 0:
                    gap.priority = max(gap.priority - 1, 1)

    def _allocate_budget(self, dimensions: list[str] | None = None) -> dict[str, int]:
        if dimensions is not None:
            return {dim: self._budget.get(dim, 1) for dim in dimensions if dim in self._enabled}
        return {dim: self._budget.get(dim, 1) for dim in self._enabled}