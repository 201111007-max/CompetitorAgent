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

# 设计文档 44：规划 LLM 化的结构化输出约束（从 core/strategic_loop.PLAN_SCHEMA 迁入）
PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["competitor"],
    "properties": {
        "competitor": {"type": "string"},
        "dimensions": {"type": "array", "items": {"type": "string", "enum": _DIM_ENUM}},
        "priorities": {"type": "object"},
        "budget": {"type": "object"},
        "custom_sources": {"type": "object"},
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
