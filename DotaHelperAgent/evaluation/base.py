"""评估器基类

定义评估器的统一接口和数据结构。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
import logging
import time

logger = logging.getLogger(__name__)


class EvaluationStatus(str, Enum):
    """评估状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ScoreDimension(str, Enum):
    """评分维度（7 维评分量表，参考 GAIA）"""

    CORRECTNESS = "correctness"
    COMPLETENESS = "completeness"
    RELEVANCE = "relevance"
    TOOL_SELECTION = "tool_selection"
    EFFICIENCY = "efficiency"
    ROBUSTNESS = "robustness"
    PERSONALIZATION = "personalization"


# 维度权重（与文档保持一致）
DIMENSION_WEIGHTS: Dict[ScoreDimension, float] = {
    ScoreDimension.CORRECTNESS: 0.25,
    ScoreDimension.COMPLETENESS: 0.15,
    ScoreDimension.RELEVANCE: 0.15,
    ScoreDimension.TOOL_SELECTION: 0.15,
    ScoreDimension.EFFICIENCY: 0.10,
    ScoreDimension.ROBUSTNESS: 0.10,
    ScoreDimension.PERSONALIZATION: 0.10,
}


@dataclass
class EvaluationContext:
    """评估上下文

    Attributes:
        case_id: 测试用例 ID
        input_data: 输入数据
        expected_output: 期望输出
        actual_output: 实际输出
        trace_id: 关联的 Trace ID
        session_id: 关联的会话 ID
        metadata: 额外元数据
    """

    case_id: str
    input_data: Any
    expected_output: Optional[Any] = None
    actual_output: Optional[Any] = None
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationResult:
    """评估结果

    Attributes:
        case_id: 测试用例 ID
        evaluator_name: 评估器名称
        status: 评估状态
        dimension_scores: 各维度评分（1-5）
        total_score: 加权总分（0-5）
        confidence: 评估置信度（0-1）
        reasoning: 评分理由
        error: 错误信息（如果失败）
        execution_time: 执行耗时（秒）
        timestamp: 评估时间戳
        metadata: 额外元数据
    """

    case_id: str
    evaluator_name: str
    status: EvaluationStatus
    dimension_scores: Dict[ScoreDimension, float] = field(default_factory=dict)
    total_score: float = 0.0
    confidence: float = 1.0
    reasoning: str = ""
    error: Optional[str] = None
    execution_time: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def calculate_total_score(self) -> float:
        """根据维度权重计算加权总分"""
        if not self.dimension_scores:
            return 0.0
        weighted_sum = sum(
            score * DIMENSION_WEIGHTS.get(dim, 0.0)
            for dim, score in self.dimension_scores.items()
        )
        return round(weighted_sum, 3)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "evaluator_name": self.evaluator_name,
            "status": self.status.value,
            "dimension_scores": {
                d.value: s for d, s in self.dimension_scores.items()
            },
            "total_score": self.total_score,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "error": self.error,
            "execution_time": self.execution_time,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class BaseEvaluator(ABC):
    """评估器抽象基类

    所有具体评估器（Judge、Trajectory、Regression）必须继承此类。
    """

    def __init__(
        self,
        name: str,
        version: str = "1.0.0",
        description: str = "",
    ):
        self.name = name
        self.version = version
        self.description = description

    @abstractmethod
    def evaluate(
        self,
        context: EvaluationContext,
    ) -> EvaluationResult:
        """执行评估（同步）

        Args:
            context: 评估上下文

        Returns:
            EvaluationResult: 评估结果
        """
        pass

    def run(
        self,
        context: EvaluationContext,
    ) -> EvaluationResult:
        """执行入口（带异常处理和计时）"""
        start_time = time.time()
        try:
            result = self.evaluate(context)
            result.execution_time = time.time() - start_time
            if not result.total_score and result.dimension_scores:
                result.total_score = result.calculate_total_score()
            return result
        except Exception as e:
            logger.error(f"Evaluator '{self.name}' failed: {e}")
            return EvaluationResult(
                case_id=context.case_id,
                evaluator_name=self.name,
                status=EvaluationStatus.FAILED,
                error=str(e),
                execution_time=time.time() - start_time,
            )
