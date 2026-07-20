"""Agent 状态定义"""
from dataclasses import dataclass, field
from typing import List, Optional
from post_match_review.types.analysis import Conclusion
from post_match_review.types.strategy import AnalysisStrategy
from post_match_review.types.match_data import MatchData


@dataclass
class ReviewAgentState:
    """复盘 Agent 状态"""
    match_id: str
    match_data: Optional[MatchData] = None
    strategy: Optional[AnalysisStrategy] = None
    completed_phases: List[str] = field(default_factory=list)
    conclusions: List[Conclusion] = field(default_factory=list)
    confidence: float = 0.0
    is_interrupted: bool = False
    total_iterations: int = 0
    total_tokens: int = 0

    def update_confidence(self) -> None:
        """基于已完成阶段重新计算整体置信度"""
        if not self.completed_phases:
            self.confidence = 0.0
            return

        # 基于结论中有证据支撑的比例估算置信度
        if not self.conclusions:
            self.confidence = 0.0
            return

        evidence_count = sum(1 for c in self.conclusions if c.has_evidence)
        evidence_ratio = evidence_count / len(self.conclusions)

        # 阶段完成度权重
        phase_count = len(self.completed_phases)
        phase_weight = min(phase_count / 4.0, 1.0)  # 假设 4 个必要阶段

        self.confidence = (evidence_ratio * 0.6 + phase_weight * 0.4)
