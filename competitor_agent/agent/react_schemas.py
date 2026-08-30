"""ReAct 结构化 Schema（设计文档 49 §3.1）

Lead Agent 规划（PLAN_SCHEMA，doc 44 迁入）、报告（REPORT_SCHEMA）、
子 Agent 结果（SUBAGENT_RESULT_SCHEMA）的 JSON Schema 契约。
details 键名沿用现有命名空间（plans/features/benchmarks/…），
使 evaluation 抽取与报告渲染不变。
"""
from __future__ import annotations

from typing import Any

# 6 个分析维度（对齐 domain_types.enums.DimensionType）
DIMENSIONS: list[str] = [
    "pricing",
    "feature",
    "performance",
    "ecosystem",
    "sentiment",
    "roadmap",
]

_DIM_ENUM: list[str] = list(DIMENSIONS)

# 设计文档 71 §8.4：format_hint 收敛为四型枚举（两阶段任务适配阶段二选"报告结构"用）。
# PLAN_SCHEMA 仍保持宽松字符串（doc 70 只定调不强制、旧 plan 兼容），
# 枚举化由 `normalize_format_hint` 在解析侧完成（非法/缺省回退 open，§11 风险 8 缓解）。
FORMAT_HINTS: list[str] = ["compare", "deep_single", "trend_tracking", "open"]

# format_hint 归一：中英关键词/别名 → 枚举值；命中失败 → "open"。
_FORMAT_HINT_ALIASES: dict[str, str] = {
    "compare": "compare", "对比": "compare", "对比型": "compare", "对比分析": "compare",
    "deep_single": "deep_single", "单体": "deep_single", "深度单体": "deep_single",
    "深度单体型": "deep_single", "单体检": "deep_single", "深挖": "deep_single",
    "trend": "trend_tracking", "trend_tracking": "trend_tracking", "变化": "trend_tracking",
    "变化追踪": "trend_tracking", "变化型": "trend_tracking", "追踪": "trend_tracking",
    "open": "open", "开放": "open", "开放型": "open", "自定义": "open",
    "": "open", "-": "open", "na": "open", "n/a": "open", "none": "open",
    "auto": "open", "default": "open",
}


def normalize_format_hint(value: object) -> str:
    """format_hint 归一（§8.4）：匹配枚举/别名 → 枚举值；非法/缺失/占位 → ``"open"``。

    ``open`` 不注入报告结构（走两段式兜底），使历史 plan（无 format_hint）与
    模型乱填保持幂等——不改变报告组装语义。
    """
    if value is None:
        return "open"
    key = str(value).strip().lower()
    if key not in _FORMAT_HINT_ALIASES:
        return "open"
    return _FORMAT_HINT_ALIASES[key]

# 设计文档 44：规划 LLM 化的结构化输出约束（从 core/strategic_loop.PLAN_SCHEMA 迁入）
# 设计文档 62 §3.1：competitor 可空，新增 competitors/resolution/scheduling——
# 单竞品（registry）用 competitor；多竞品（compare/discovery）用 competitors；
# resolution 是编排起点标注（querySource 语义），scheduling 是 Lead 的并行意图提示。
# competitor XOR competitors 由 make_plan 工具手动校验（schema 保持宽松，缺省即合法）。
PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [],
    "properties": {
        "competitor": {"type": "string"},
        "competitors": {"type": "array", "items": {"type": "string"}},
        "dimensions": {"type": "array", "items": {"type": "string", "enum": _DIM_ENUM}},
        "priorities": {"type": "object"},
        "budget": {"type": "object"},
        "custom_sources": {"type": "object"},
        "resolution": {"type": "string", "enum": ["registry", "discovery", "compare"]},
        "scheduling": {
            "type": ["object", "null"],
            "properties": {
                "parallel": {"type": "boolean"},
                "reason": {"type": "string"},
            },
        },
        # 设计文档 70 M2 规划层意图/格式决策（全可选，只定调不强制）：
        # output_intent = 给谁看/目的（CTO 选型/投资人/自己备忘…）；format_hint = 问题类型定调
        # （对比型/深度单体型/变化追踪型/开放型）；need_history = 是否需要检索历史（"和上次比变化"类）。
        "output_intent": {"type": "string"},
        "format_hint": {"type": "string"},
        "need_history": {"type": "boolean"},
    },
}

# 单个维度结论条目（Lead Final Answer dimensions 与子 Agent Final Answer 共用）
_DIMENSION_RESULT_ITEM: dict[str, Any] = {
    "type": "object",
    "required": ["dimension", "summary", "details", "confidence"],
    "properties": {
        "dimension": {"type": "string", "enum": _DIM_ENUM},
        "summary": {"type": "string"},
        "details": {"type": "object"},
        "confidence": {"type": "number"},
        "evidence_urls": {"type": "array", "items": {"type": "string"}},
    },
}

# Lead Final Answer：整份竞品分析报告
REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["competitor", "dimensions"],
    "properties": {
        "competitor": {"type": "string"},
        "dimensions": {"type": "array", "items": _DIMENSION_RESULT_ITEM},
    },
}

# 子 Agent Final Answer：单个维度结果（含证据 URL 供记忆写侧/报告组装）
SUBAGENT_RESULT_SCHEMA: dict[str, Any] = dict(_DIMENSION_RESULT_ITEM)
