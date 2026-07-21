"""停止验证接口"""
from typing import Protocol
from post_match_review.domain_types.events import VerificationResult
from post_match_review.domain_types.state import ReviewAgentState


class IStopVerifier(Protocol):
    """停止验证器接口"""

    def verify(self, state: ReviewAgentState) -> VerificationResult:
        """验证是否满足终止条件

        Args:
            state: 当前 Agent 状态

        Returns:
            VerificationResult: 验证结果
        """
        ...
