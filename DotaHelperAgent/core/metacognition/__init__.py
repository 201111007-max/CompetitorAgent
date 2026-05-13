"""元认知能力模块 - 让 Agent 具备自我评估能力

核心功能：
- 知识边界评估：判断 Agent 是否知道答案
- 置信度计算：评估回答的可信度
- 澄清请求生成：主动向用户请求更多信息

架构设计：
- 接口优先：所有核心组件定义抽象接口
- 策略模式：评估策略、置信度计算、澄清生成均可替换
- 依赖注入：通过配置组装不同实现
"""

from .interfaces import (
    IKnowledgeBoundary,
    IConfidenceCalculator,
    IClarificationGenerator,
    IMetacognitionEvaluator,
    KnowledgeAssessment,
    ClarificationRequest,
    ConfidenceLevel
)
from .rule_based import (
    RuleBasedKnowledgeBoundary,
    WeightedConfidenceCalculator,
    RuleBasedClarificationGenerator,
    RuleBasedMetacognitionEvaluator
)
from .factory import MetacognitionFactory

__all__ = [
    # 接口
    "IKnowledgeBoundary",
    "IConfidenceCalculator",
    "IClarificationGenerator",
    "IMetacognitionEvaluator",
    "KnowledgeAssessment",
    "ClarificationRequest",
    "ConfidenceLevel",
    
    # 规则驱动实现
    "RuleBasedKnowledgeBoundary",
    "WeightedConfidenceCalculator",
    "RuleBasedClarificationGenerator",
    "RuleBasedMetacognitionEvaluator",
    
    # 工厂
    "MetacognitionFactory"
]
