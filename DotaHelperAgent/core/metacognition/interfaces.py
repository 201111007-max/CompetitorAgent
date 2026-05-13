"""元认知能力接口定义

职责：
- 定义所有核心接口，确保组件可替换
- 定义数据结构，统一数据格式

扩展方式：
- 实现接口创建新的评估策略
- 继承数据类扩展字段
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import time


class ConfidenceLevel(Enum):
    """置信度等级
    
    用于标识 Agent 对回答的自信程度
    """
    VERY_HIGH = "very_high"    # 0.9 - 1.0：极其确定
    HIGH = "high"              # 0.7 - 0.9：高度确定
    MEDIUM = "medium"          # 0.5 - 0.7：中等确定
    LOW = "low"                # 0.3 - 0.5：不太确定
    VERY_LOW = "very_low"      # 0.0 - 0.3：极不确定


@dataclass
class KnowledgeAssessment:
    """知识评估结果
    
    属性：
        confidence_score: 综合置信度分数 (0.0 - 1.0)
        confidence_level: 置信度等级
        knowledge_coverage: 知识覆盖度 (0.0 - 1.0)
        data_quality_score: 数据质量评分 (0.0 - 1.0)
        reasoning: 评估理由说明
        limitations: 已知限制列表
        data_sources: 使用的数据源列表
        timestamp: 评估时间戳
    """
    confidence_score: float
    confidence_level: ConfidenceLevel
    knowledge_coverage: float
    data_quality_score: float
    reasoning: str
    limitations: List[str] = field(default_factory=list)
    data_sources: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "confidence_score": round(self.confidence_score, 3),
            "confidence_level": self.confidence_level.value,
            "knowledge_coverage": round(self.knowledge_coverage, 3),
            "data_quality_score": round(self.data_quality_score, 3),
            "reasoning": self.reasoning,
            "limitations": self.limitations,
            "data_sources": self.data_sources,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeAssessment":
        """从字典创建"""
        return cls(
            confidence_score=data["confidence_score"],
            confidence_level=ConfidenceLevel(data["confidence_level"]),
            knowledge_coverage=data["knowledge_coverage"],
            data_quality_score=data["data_quality_score"],
            reasoning=data["reasoning"],
            limitations=data.get("limitations", []),
            data_sources=data.get("data_sources", []),
            timestamp=data.get("timestamp", time.time())
        )


@dataclass
class ClarificationRequest:
    """澄清请求
    
    当 Agent 知识不足时，向用户请求更多信息
    
    属性：
        type: 澄清类型标识
        original_query: 用户原始查询
        confidence_level: 当前置信度等级
        missing_info: 缺失信息列表
        questions: 澄清问题列表
        suggestions: 建议用户操作列表
        partial_answer: 部分答案（如果有）
    """
    type: str
    original_query: str
    confidence_level: ConfidenceLevel
    missing_info: List[str]
    questions: List[str]
    suggestions: List[str]
    partial_answer: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "type": self.type,
            "original_query": self.original_query,
            "confidence_level": self.confidence_level.value,
            "missing_info": self.missing_info,
            "questions": self.questions,
            "suggestions": self.suggestions,
            "partial_answer": self.partial_answer
        }


class IKnowledgeBoundary(ABC):
    """知识边界评估接口
    
    职责：
    - 评估 Agent 对特定问题的知识掌握程度
    - 识别知识盲区
    - 评估数据质量和覆盖度
    
    扩展方式：
    - 实现此接口创建新的知识边界评估策略
    - 例如：RuleBasedKnowledgeBoundary, LLMBasedKnowledgeBoundary, MLBasedKnowledgeBoundary
    """
    
    @abstractmethod
    def assess(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> KnowledgeAssessment:
        """评估知识掌握程度
        
        Args:
            query: 用户查询
            context: 上下文信息（包含英雄、物品、数据源等）
            
        Returns:
            KnowledgeAssessment: 知识评估结果
        """
        pass


class IConfidenceCalculator(ABC):
    """置信度计算器接口
    
    职责：
    - 综合多维度因素计算最终置信度
    - 提供置信度等级划分
    
    扩展方式：
    - 实现此接口创建新的置信度计算策略
    - 例如：WeightedConfidenceCalculator, MLConfidenceCalculator, FuzzyConfidenceCalculator
    """
    
    @abstractmethod
    def calculate(
        self,
        factors: Dict[str, float],
        weights: Optional[Dict[str, float]] = None
    ) -> float:
        """计算置信度
        
        Args:
            factors: 影响因素字典 {factor_name: score}
                    常见因素：knowledge_coverage, data_quality, tool_match, memory_relevance
            weights: 权重配置 {factor_name: weight}，如果为 None 则使用默认权重
            
        Returns:
            float: 置信度分数 (0.0 - 1.0)
        """
        pass
    
    @abstractmethod
    def get_level(self, score: float) -> ConfidenceLevel:
        """根据分数获取置信度等级
        
        Args:
            score: 置信度分数 (0.0 - 1.0)
            
        Returns:
            ConfidenceLevel: 置信度等级
        """
        pass


class IClarificationGenerator(ABC):
    """澄清请求生成器接口
    
    职责：
    - 根据知识缺口生成结构化的澄清请求
    - 提供针对性的澄清问题
    - 生成用户友好的建议操作
    
    扩展方式：
    - 实现此接口创建新的澄清请求生成策略
    - 例如：RuleBasedClarificationGenerator, LLMClarificationGenerator
    """
    
    @abstractmethod
    def generate(
        self,
        query: str,
        assessment: KnowledgeAssessment,
        missing_info: List[str]
    ) -> ClarificationRequest:
        """生成澄清请求
        
        Args:
            query: 用户查询
            assessment: 知识评估结果
            missing_info: 缺失信息列表
            
        Returns:
            ClarificationRequest: 澄清请求
        """
        pass


class IMetacognitionEvaluator(ABC):
    """元认知评估器接口（主接口）
    
    职责：
    - 协调各个组件完成完整的元认知评估流程
    - 提供执行前、执行中、执行后的评估能力
    - 判断是否需要请求用户澄清
    
    扩展方式：
    - 实现此接口创建新的元认知评估器
    - 例如：RuleBasedMetacognitionEvaluator, LLMBasedMetacognitionEvaluator
    
    使用示例：
    ```python
    evaluator = MetacognitionFactory.create_evaluator(config, ...)
    
    # 执行前评估
    assessment = evaluator.assess_before_execution(query, context)
    if evaluator.should_request_clarification(assessment):
        clarification = evaluator.generate_clarification(query, assessment)
        return clarification
    
    # 执行中评估
    assessment = evaluator.assess_during_execution(query, observations, actions, context)
    
    # 执行后评估
    assessment = evaluator.assess_after_execution(query, final_result, context)
    ```
    """
    
    @abstractmethod
    def assess_before_execution(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> KnowledgeAssessment:
        """执行前评估
        
        在 ReAct 循环开始前评估是否有足够知识回答问题
        
        Args:
            query: 用户查询
            context: 上下文信息
            
        Returns:
            KnowledgeAssessment: 知识评估结果
        """
        pass
    
    @abstractmethod
    def assess_during_execution(
        self,
        query: str,
        observations: List[Any],
        actions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> KnowledgeAssessment:
        """执行中评估
        
        在 ReAct 循环执行过程中评估当前进展
        
        Args:
            query: 用户查询
            observations: 已收集的观察结果
            actions: 已执行的工具调用
            context: 上下文信息
            
        Returns:
            KnowledgeAssessment: 知识评估结果
        """
        pass
    
    @abstractmethod
    def assess_after_execution(
        self,
        query: str,
        final_result: Dict[str, Any],
        context: Dict[str, Any]
    ) -> KnowledgeAssessment:
        """执行后评估
        
        在 ReAct 循环完成后评估最终结果的可信度
        
        Args:
            query: 用户查询
            final_result: 最终执行结果
            context: 上下文信息
            
        Returns:
            KnowledgeAssessment: 知识评估结果
        """
        pass
    
    @abstractmethod
    def should_request_clarification(
        self,
        assessment: KnowledgeAssessment
    ) -> bool:
        """判断是否需要请求用户澄清
        
        Args:
            assessment: 知识评估结果
            
        Returns:
            bool: 是否需要请求澄清
        """
        pass
    
    @abstractmethod
    def generate_clarification(
        self,
        query: str,
        assessment: KnowledgeAssessment
    ) -> ClarificationRequest:
        """生成澄清请求
        
        Args:
            query: 用户查询
            assessment: 知识评估结果
            
        Returns:
            ClarificationRequest: 澄清请求
        """
        pass
