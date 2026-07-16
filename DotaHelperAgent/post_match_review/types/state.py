"""Agent 状态定义"""
from dataclasses import dataclass, field
from typing import List, Optional
from post_match_review.types.analysis import AnalysisStrategy, Conclusion
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
        """基于当前结论重新计算整体置信度"""
        if not self.conclusions:
            self.confidence = 0.0
            return
        
        # 计算所有结论的加权平均置信度
        total_confidence = sum(c.confidence for c in self.conclusions)
        self.confidence = total_confidence / len(self.conclusions)
