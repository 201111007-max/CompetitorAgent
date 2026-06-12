"""知识管理系统

提供向量数据库、知识融合、知识查询等功能
"""

from .entity_alignment import EntityAlignment
from .conflict_detector import ConflictDetector
from .confidence_evaluator import ConfidenceEvaluator

# 延迟导入，避免循环依赖
__all__ = [
    'VectorStore',
    'KnowledgeFusionEngine',
    'FusedKnowledge',
    'EntityAlignment',
    'ConflictDetector',
    'ConfidenceEvaluator'
]


def __getattr__(name):
    """延迟导入模块"""
    if name == 'VectorStore':
        from .vector_store import VectorStore
        return VectorStore
    elif name == 'KnowledgeFusionEngine':
        from .fusion_engine import KnowledgeFusionEngine
        return KnowledgeFusionEngine
    elif name == 'FusedKnowledge':
        from .fusion_engine import FusedKnowledge
        return FusedKnowledge
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
