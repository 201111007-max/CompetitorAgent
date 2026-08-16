"""StrategicLoop — 战略循环：任务 → 信息缺口清单 + 预算分配

规则版（M1 无 LLM）：
1. 解析任务识别竞品（注册表 + 规则）
2. 生成 InfoGap 清单（按维度默认优先级 + 初始置信度 0）
3. 按 config 分配维度预算
4. 产出 CompetitorStrategy

LLM 版规划（设计文档 44 §3.2）：plan() 走一次结构化 complete_json
（competitor/dimensions/priorities/budget/custom_sources，PLAN_SCHEMA 约束），
规则为降级（LLM 不可用/非法输入回退 _plan_with_rules）。
"""
from __future__ import annotations

import logging
from typing import Any

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

# 设计文档 44：规划 LLM 化的结构化输出约束（JSON Schema 子集，复用 34 complete_json）
_PLAN_DIM_ENUM = ["pricing", "feature", "performance", "ecosystem", "sentiment", "roadmap"]
PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["competitor"],
    "properties": {
        "competitor": {"type": "string"},
        "dimensions": {"type": "array", "items": {"type": "string", "enum": _PLAN_DIM_ENUM}},
        "priorities": {"type": "object"},
        "budget": {"type": "object"},
        "custom_sources": {"type": "object"},
    },
}

_PLAN_PROMPT = (
    "你是竞品分析战略规划器。根据用户任务规划竞品分析策略，只输出 JSON，不要其他文字。\n"
    'JSON 格式: {"competitor": "竞品规范名", '
    '"dimensions": ["pricing","feature","performance","ecosystem","sentiment","roadmap"]（可选，缺省=全部维度）, '
    '"priorities": {"维度名": 1-10 整数}（可选，缺省用默认）, '
    '"budget": {"维度名": 迭代次数整数}（可选，缺省每维度 1）, '
    '"custom_sources": {"home或pricing或docs": "用户提供的URL"}}（可选）。\n'
    "规则：只列任务明确要求的维度（如任务只说定价就只列 pricing）；任务没提维度则列出全部 6 个维度；"
    "priorities 体现任务侧重（如强调价格则 pricing 优先）。"
)


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
        """解析任务 → 竞品 + 缺口清单 + 预算。

        设计文档 44 §3.2：LLM 可用时一次结构化规划（competitor/dimensions/priorities/budget），
        LLM 不可用 / 非法输入回退规则版（_plan_with_rules，行为与现状一致）。
        """
        if self._use_llm and self._llm is not None:
            try:
                parsed = self._llm.complete_json(
                    self._plan_messages(task, memory), schema=PLAN_SCHEMA
                )
                return self._strategy_from_llm(parsed, memory)
            except Exception as exc:  # noqa: BLE001 — LLM 规划任何失败/非法输入回退规则版
                logger.warning("LLM 规划失败，回退规则版: %s", exc)
        return self._plan_with_rules(task, memory)

    def _plan_with_rules(
        self, task: str, memory: IFourLayerMemory | None = None
    ) -> CompetitorStrategy:
        """规则版规划（现状路径）：parse_task 仅用规则解析（不二次调 LLM）。"""
        parsed = parse_task(task, use_llm=False)
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

    # ── 设计文档 44：规划 LLM 化 ─────────────────────────────────────

    def _plan_messages(self, task: str, memory: IFourLayerMemory | None) -> list[dict[str, str]]:
        """规划 prompt：任务 + 可选历史经验参考（失败静默省略）。"""
        content = _PLAN_PROMPT
        context = self._plan_memory_context(task, memory)
        if context:
            content += f"\n\n[历史经验参考（本系统沉淀的过往结论，仅作参考）]\n{context}"
        return [{"role": "user", "content": content}]

    def _plan_memory_context(self, task: str, memory: IFourLayerMemory | None) -> str:
        """规划记忆召回（recent_context，设计文档 35）：按规则预判竞品召回历史结论。"""
        if memory is None:
            return ""
        recall = getattr(memory, "recent_context", None)
        if not callable(recall):
            return ""
        try:
            competitor = parse_task(task, use_llm=False).primary_competitor
        except Exception:  # noqa: BLE001 — 竞品预判失败不影响规划 prompt
            return ""
        if not competitor or competitor == "unknown":
            return ""
        try:
            return "\n".join(recall(competitor, top_k=3, query=task))
        except Exception:  # noqa: BLE001 — 记忆召回失败不影响规划
            logger.warning("规划记忆召回失败: %s", competitor)
            return ""

    def _strategy_from_llm(
        self,
        parsed: dict[str, Any],
        memory: IFourLayerMemory | None,
    ) -> CompetitorStrategy:
        """把 LLM 规划结果转为 CompetitorStrategy（复用记忆提权/降权，非法输入抛错回退规则）。"""
        competitor = self._competitor_from_llm(parsed)
        dimensions = self._dimensions_from_llm(parsed)
        gaps = self._gaps_from_llm(parsed, dimensions)
        self._apply_memory_boost(gaps, competitor, memory)
        self._apply_pattern_boost(gaps, competitor, memory)
        budget = self._llm_budget(parsed.get("budget"), dimensions)
        return CompetitorStrategy(
            competitor=competitor,
            gaps=gaps,
            budget_allocation={
                DimensionType(dim): n for dim, n in budget.items() if dim in self._enabled
            },
            terminal_thresholds={"confidence": 0.8},
        )

    def _competitor_from_llm(self, parsed: dict[str, Any]) -> Competitor:
        name = str(parsed.get("competitor") or "").strip()
        if not name or name.lower() in ("unknown", "未知"):
            raise ValueError("LLM 规划未识别竞品")
        competitor = resolve_competitor(name)
        custom = {
            str(k): str(v) for k, v in (parsed.get("custom_sources") or {}).items() if v
        }
        if not custom:
            return competitor
        links = dict(competitor.official_links)
        links.update(custom)
        return Competitor(
            name=competitor.name,
            aliases=competitor.aliases,
            category=competitor.category,
            official_links=links,
        )

    def _dimensions_from_llm(self, parsed: dict[str, Any]) -> list[str]:
        raw = parsed.get("dimensions")
        if isinstance(raw, list) and raw:
            valid = [d for d in raw if d in DIMENSION_PRIORITY and d in self._enabled]
            if valid:
                return valid
        return list(self._enabled)

    def _gaps_from_llm(self, parsed: dict[str, Any], dimensions: list[str]) -> list[InfoGap]:
        raw_priorities = parsed.get("priorities")
        priorities = raw_priorities if isinstance(raw_priorities, dict) else {}
        gaps = []
        for dim in dimensions:
            priority = self._coerce_priority(priorities.get(dim), DIMENSION_PRIORITY[dim])
            gaps.append(
                InfoGap(field=dim, priority=priority, confidence=0.0, status=GapStatus.OPEN)
            )
        return gaps

    @staticmethod
    def _coerce_priority(raw: Any, default: int) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default
        return max(1, min(10, value))

    @staticmethod
    def _llm_budget(raw: Any, dimensions: list[str]) -> dict[str, int]:
        """LLM 预算分配：缺失维度兜底 1（设计文档 44 §3.2），越界收敛到 [1,5]。"""
        source = raw if isinstance(raw, dict) else {}
        budget: dict[str, int] = {}
        for dim in dimensions:
            raw_n = source.get(dim)
            if raw_n is None:
                n = 1
            else:
                try:
                    n = int(raw_n)
                except (TypeError, ValueError):
                    n = 1
            budget[dim] = max(1, min(n, 5))
        return budget

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