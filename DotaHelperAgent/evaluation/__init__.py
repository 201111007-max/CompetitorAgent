"""评测系统

为 DotaHelperAgent 提供三层评估能力：
- L1 离线评测（开发阶段）：标准测试集 + 单元/集成测试
- L2 在线评测（生产阶段）：Trace + 用户反馈
- L3 回归测试（发布阶段）：基线对比 + A/B 测试

核心组件：
- BaseEvaluator: 评估器抽象基类
- LLM-as-a-Judge: 7 维评分
- Trajectory Evaluator: 轨迹评估
- Regression Tester: 回归测试
- DotaBench: 自建评测集
"""

from .base import (
    BaseEvaluator,
    EvaluationContext,
    EvaluationResult,
    EvaluationStatus,
    ScoreDimension,
)

__all__ = [
    "BaseEvaluator",
    "EvaluationContext",
    "EvaluationResult",
    "EvaluationStatus",
    "ScoreDimension",
]
