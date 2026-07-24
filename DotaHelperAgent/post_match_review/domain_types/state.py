"""Agent 状态定义"""
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from post_match_review.domain_types.analysis import Conclusion
from post_match_review.domain_types.strategy import AnalysisStrategy
from post_match_review.domain_types.match_data import MatchData


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

    # P1-1: 序列化/反序列化支持（中断恢复）
    def to_dict(self) -> Dict[str, Any]:
        """将状态序列化为字典

        Returns:
            Dict[str, Any]: 可 JSON 序列化的状态字典
        """
        result: Dict[str, Any] = {
            "match_id": self.match_id,
            "completed_phases": self.completed_phases,
            "confidence": self.confidence,
            "is_interrupted": self.is_interrupted,
            "total_iterations": self.total_iterations,
            "total_tokens": self.total_tokens,
        }

        # 序列化结论
        result["conclusions"] = [asdict(c) for c in self.conclusions]

        # match_data 和 strategy 可能不可序列化，仅保存标识
        if self.match_data is not None:
            result["match_data_id"] = self.match_data.match_id
        if self.strategy is not None:
            result["strategy_match_type"] = self.strategy.match_type

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewAgentState":
        """从字典反序列化状态

        Args:
            data: 序列化的状态字典

        Returns:
            ReviewAgentState: 恢复的状态实例
        """
        state = cls(match_id=data["match_id"])
        state.completed_phases = data.get("completed_phases", [])
        state.confidence = data.get("confidence", 0.0)
        state.is_interrupted = data.get("is_interrupted", False)
        state.total_iterations = data.get("total_iterations", 0)
        state.total_tokens = data.get("total_tokens", 0)

        # 反序列化结论
        for c_data in data.get("conclusions", []):
            state.conclusions.append(Conclusion(**c_data))

        return state
