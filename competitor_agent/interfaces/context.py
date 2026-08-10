"""契约层共享上下文/信令类型"""
from __future__ import annotations

from dataclasses import dataclass, field

from competitor_agent.domain_types.enums import DimensionType


@dataclass
class SourceContext:
    """采集上下文：携带竞品线索与检索参数"""

    competitor_name: str
    query: str = ""
    kwargs: dict[str, object] = field(default_factory=dict)


@dataclass
class AnalysisContext:
    """分析上下文：跨维度共享的会话信息"""

    competitor_name: str = ""
    dimension: DimensionType | None = None
    history: list[object] = field(default_factory=list)
    rag_context: str = ""  # RAG 检索到的背景知识片段（含来源），注入分析器 prompt


@dataclass
class BudgetState:
    """预算状态快照（供验证器共享）"""

    iterations_used: int = 0
    total_cost: float = 0.0
    max_iterations: int = 1
    cost_limit: float = 1.0


@dataclass
class StopDecision:
    """终止决策（验证器可做出的裁定）"""

    should_stop: bool
    reason: str = ""
    details: str = ""


@dataclass
class AnalysisSession:
    """一次分析会话（记忆 L1 归档载荷）"""

    task: str
    competitor_name: str
    session_id: str = ""
    created_at: str = ""
    raw: dict[str, object] = field(default_factory=dict)


@dataclass
class Skill:
    """沉淀技能（L3）：竞品×维度下哪个数据源更有效"""

    competitor_name: str
    gap_field: str
    source_name: str
    success: bool = True
    weight: float = 0.0


@dataclass
class ChatMessage:
    """消息（供上下文压缩器使用）"""

    role: str  # system / user / assistant / tool
    content: str
    name: str | None = None