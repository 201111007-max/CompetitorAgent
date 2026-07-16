"""停止验证器"""
from typing import List
from post_match_review.interfaces.verifier import IStopVerifier
from post_match_review.types.events import VerificationResult
from post_match_review.types.state import ReviewAgentState
from post_match_review.observability.logger import get_logger

logger = get_logger("engines.stop_verifier")


class StopVerifier(IStopVerifier):
    """停止验证器（三段验证）"""

    def __init__(
        self,
        required_phases: List[str],
        min_confidence: float = 0.6,
        max_verification_retries: int = 2,
    ) -> None:
        """初始化停止验证器

        Args:
            required_phases: 必须完成的分析阶段列表
            min_confidence: 最低置信度要求
            max_verification_retries: 最大验证重试次数
        """
        self._required_phases = required_phases
        self._min_confidence = min_confidence
        self._max_verification_retries = max_verification_retries
        
        logger.info(
            "停止验证器初始化: required_phases=%s, min_confidence=%.2f",
            required_phases,
            min_confidence,
        )

    def verify(self, state: ReviewAgentState) -> VerificationResult:
        """执行三段验证

        Args:
            state: 当前 Agent 状态

        Returns:
            VerificationResult: 验证结果
        """
        blocking_reasons: List[str] = []
        suggestions: List[str] = []

        # 检查 1: 必要阶段是否全部完成
        missing_phases = [
            phase for phase in self._required_phases 
            if phase not in state.completed_phases
        ]
        if missing_phases:
            blocking_reasons.append(f"缺少必要分析阶段: {', '.join(missing_phases)}")
            suggestions.append(f"请完成以下阶段: {', '.join(missing_phases)}")

        # 检查 2: 每个结论是否有数据支撑
        conclusions_without_evidence = [
            c for c in state.conclusions if not c.has_evidence
        ]
        if conclusions_without_evidence:
            blocking_reasons.append(
                f"{len(conclusions_without_evidence)} 个结论缺少数据支撑"
            )
            suggestions.append("为每个结论提供具体的数据证据")

        # 检查 3: 整体置信度是否达标
        if state.confidence < self._min_confidence:
            blocking_reasons.append(
                f"整体置信度 {state.confidence:.2f} 低于要求 {self._min_confidence:.2f}"
            )
            suggestions.append("继续分析以提高置信度")

        # 判断是否通过
        passed = len(blocking_reasons) == 0

        if passed:
            logger.info("停止验证通过: confidence=%.2f", state.confidence)
        else:
            logger.warning(
                "停止验证未通过: %d 个阻塞原因",
                len(blocking_reasons),
            )

        return VerificationResult(
            passed=passed,
            blocking_reasons=blocking_reasons,
            suggestions=suggestions,
        )
