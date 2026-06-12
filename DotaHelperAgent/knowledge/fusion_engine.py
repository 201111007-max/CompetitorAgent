"""知识融合引擎 - 整合多源知识"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

from utils.log_config import get_logger
from .entity_alignment import EntityAlignment
from .conflict_detector import ConflictDetector
from .confidence_evaluator import ConfidenceEvaluator

logger = get_logger("fusion_engine", component="knowledge")


@dataclass
class FusedKnowledge:
    """融合后的知识"""
    query: str
    structured_knowledge: List[Dict[str, Any]]
    unstructured_knowledge: List[Dict[str, Any]]
    conflicts: List[Dict[str, Any]]
    confidence: float
    sources: List[str]
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式

        Returns:
            字典表示
        """
        return {
            'query': self.query,
            'structured_knowledge': self.structured_knowledge,
            'unstructured_knowledge': self.unstructured_knowledge,
            'conflicts': self.conflicts,
            'confidence': self.confidence,
            'sources': self.sources,
            'timestamp': self.timestamp
        }


class KnowledgeFusionEngine:
    """知识融合引擎

    功能：
    - 实体对齐
    - 冲突检测
    - 置信度评估
    - 知识融合
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """初始化知识融合引擎

        Args:
            config: 配置字典
        """
        self.config = config or {}
        self.entity_alignment = EntityAlignment()
        self.conflict_detector = ConflictDetector()
        self.confidence_evaluator = ConfidenceEvaluator()

        logger.info("知识融合引擎初始化完成")

    def merge(
        self,
        structured_knowledge: List[Dict[str, Any]],
        unstructured_knowledge: List[Dict[str, Any]],
        query: str
    ) -> FusedKnowledge:
        """融合结构化和非结构化知识

        Args:
            structured_knowledge: 结构化知识（来自知识图谱）
            unstructured_knowledge: 非结构化知识（来自向量检索）
            query: 查询文本

        Returns:
            融合后的知识
        """
        logger.info(f"开始知识融合: 查询='{query}'")

        # 1. 实体对齐
        aligned_structured = self._align_entities(structured_knowledge)
        aligned_unstructured = self._align_entities(unstructured_knowledge)

        # 2. 冲突检测
        all_knowledge = aligned_structured + aligned_unstructured
        conflicts = self.conflict_detector.detect(all_knowledge)

        # 3. 置信度评估
        for knowledge in all_knowledge:
            knowledge['confidence'] = self.confidence_evaluator.evaluate(knowledge)

        # 4. 计算综合置信度
        overall_confidence = self._calculate_overall_confidence(all_knowledge)

        # 5. 收集数据源
        sources = list(set([k.get('source', 'unknown') for k in all_knowledge]))

        # 6. 构建融合结果
        fused_knowledge = FusedKnowledge(
            query=query,
            structured_knowledge=aligned_structured,
            unstructured_knowledge=aligned_unstructured,
            conflicts=conflicts,
            confidence=overall_confidence,
            sources=sources,
            timestamp=datetime.now().timestamp()
        )

        logger.info(f"知识融合完成: 置信度={overall_confidence:.2f}, 冲突数={len(conflicts)}")
        return fused_knowledge

    def _align_entities(self, knowledge_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """实体对齐

        Args:
            knowledge_list: 知识列表

        Returns:
            对齐后的知识列表
        """
        aligned = []
        for knowledge in knowledge_list:
            aligned_knowledge = knowledge.copy()

            # 对齐英雄名称
            if 'hero' in aligned_knowledge:
                aligned_knowledge['hero'] = self.entity_alignment.align(
                    aligned_knowledge['hero'],
                    entity_type="hero"
                )

            # 对齐物品名称
            if 'item' in aligned_knowledge:
                aligned_knowledge['item'] = self.entity_alignment.align(
                    aligned_knowledge['item'],
                    entity_type="item"
                )

            # 对齐技能名称
            if 'skill' in aligned_knowledge:
                aligned_knowledge['skill'] = self.entity_alignment.align(
                    aligned_knowledge['skill'],
                    entity_type="ability"
                )

            aligned.append(aligned_knowledge)

        return aligned

    def _calculate_overall_confidence(self, knowledge_list: List[Dict[str, Any]]) -> float:
        """计算综合置信度

        Args:
            knowledge_list: 知识列表

        Returns:
            综合置信度
        """
        if not knowledge_list:
            return 0.0

        confidences = [k.get('confidence', 0.5) for k in knowledge_list]
        return sum(confidences) / len(confidences)

    def get_knowledge_summary(self, fused_knowledge: FusedKnowledge) -> str:
        """获取知识摘要

        Args:
            fused_knowledge: 融合后的知识

        Returns:
            知识摘要文本
        """
        summary_parts = []

        # 添加查询信息
        summary_parts.append(f"查询: {fused_knowledge.query}")

        # 添加结构化知识摘要
        if fused_knowledge.structured_knowledge:
            summary_parts.append(f"\n结构化知识 ({len(fused_knowledge.structured_knowledge)} 条):")
            for i, k in enumerate(fused_knowledge.structured_knowledge[:3], 1):
                summary_parts.append(f"  {i}. {k}")

        # 添加非结构化知识摘要
        if fused_knowledge.unstructured_knowledge:
            summary_parts.append(f"\n非结构化知识 ({len(fused_knowledge.unstructured_knowledge)} 条):")
            for i, k in enumerate(fused_knowledge.unstructured_knowledge[:3], 1):
                summary_parts.append(f"  {i}. {k}")

        # 添加冲突信息
        if fused_knowledge.conflicts:
            summary_parts.append(f"\n检测到冲突: {len(fused_knowledge.conflicts)} 个")

        # 添加置信度
        summary_parts.append(f"\n综合置信度: {fused_knowledge.confidence:.2f}")

        return "\n".join(summary_parts)
