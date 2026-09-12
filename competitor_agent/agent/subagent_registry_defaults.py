"""coding_agent 领域的内联默认（设计文档 79 §2.2 兜底层）。

pack yaml（``config/domains/coding_agent.yaml``）缺失/损坏时的回退——内容与
下沉前的硬编码 dict 逐位一致（L1 `_SUBAGENT_TOOLS/_SUBAGENT_SKILLS/_SUBAGENT_DESCRIPTIONS`
+ L3 维度枚举 + L2 权重）。作为「现状等价改写」的回归基线。
"""
from __future__ import annotations

from competitor_agent.agent.react_schemas import DIMENSIONS
from competitor_agent.core.domain_pack import DimensionSpec, DomainPack, RegistrySeed

# 工具子集白名单：pricing 含定价工具，ecosystem/roadmap 含 github 系列。
# 一律排除 analyze_competitor（防递归调用 analyze()）。
_SUBAGENT_TOOLS: dict[str, list[str]] = {
    "pricing": ["web_extract", "web_search", "analyze_pricing"],
    "feature": ["web_extract", "web_search"],
    # 设计文档 67 §2.1：performance 加结构化榜单直连工具（替代 LLM 读网页）
    "performance": ["web_extract", "web_search", "benchmark_scores"],
    "ecosystem": ["web_extract", "web_search", "github_stars", "github_releases", "github_commits"],
    # 设计文档 67 §2.2：sentiment 加结构化采样工具（带样本量/时间窗）
    "sentiment": ["web_extract", "web_search", "sentiment_sampling"],
    "roadmap": ["web_extract", "web_search", "github_releases", "github_commits"],
}

# skill 注入清单：维度抽取 + 事实边界 + 置信度披露
_SUBAGENT_SKILLS: dict[str, list[str]] = {
    dim: [f"{dim}_analysis", "fact_verification", "confidence_disclosure"]
    for dim in DIMENSIONS
}

_SUBAGENT_DESCRIPTIONS: dict[str, str] = {
    "pricing": "分析竞品定价：套餐档位、按量计费、月付/年付价格与成本场景估算。",
    "feature": "分析竞品核心功能矩阵与特性。",
    "performance": "分析竞品性能：榜单、延迟、胜率等基准数据。",
    "ecosystem": "分析竞品生态：MCP server 数量、IDE/插件支持、GitHub 社区活跃度。",
    "sentiment": "分析竞品口碑：正负极性、社区评价。",
    "roadmap": "分析竞品路线图与版本发布节奏。",
}

# 维度权重（core/report_builder._DIMENSION_WEIGHTS 的 L2 下沉源）
CODING_DIMENSION_WEIGHTS: dict[str, float] = {
    "pricing": 0.25,
    "feature": 0.25,
    "performance": 0.2,
    "ecosystem": 0.1,
    "sentiment": 0.1,
    "roadmap": 0.1,
}

_dimensions = tuple(
    DimensionSpec(
        name=dim,
        description=_SUBAGENT_DESCRIPTIONS[dim],
        tools=tuple(_SUBAGENT_TOOLS[dim]),
        skills=tuple(_SUBAGENT_SKILLS[dim]),
    )
    for dim in DIMENSIONS
)

CODING_DIMENSIONS = DomainPack(
    domain="coding_agent",
    category_label="ai_coding_agent",
    dimensions=_dimensions,
    registry_seeds=(),  # 注册表种子以内联回退维护于 core/competitor_registry._FALLBACK_SEEDS
    default_dimension_weights=dict(CODING_DIMENSION_WEIGHTS),
)

__all__ = [
    "CODING_DIMENSIONS",
    "CODING_DIMENSION_WEIGHTS",
    "_SUBAGENT_DESCRIPTIONS",
    "_SUBAGENT_SKILLS",
    "_SUBAGENT_TOOLS",
    "RegistrySeed",
]
