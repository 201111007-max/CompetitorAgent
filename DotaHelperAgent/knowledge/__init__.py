"""知识管理系统

提供向量数据库、知识融合、知识查询等功能
"""

from .vector_store import VectorStore
from .fusion_engine import KnowledgeFusionEngine, FusedKnowledge
from .entity_alignment import EntityAlignment
from .conflict_detector import ConflictDetector
from .confidence_evaluator import ConfidenceEvaluator

__all__ = [
    'VectorStore',
    'KnowledgeFusionEngine',
    'FusedKnowledge',
    'EntityAlignment',
    'ConflictDetector',
    'ConfidenceEvaluator'
]
