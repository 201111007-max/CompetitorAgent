"""复盘报告类型定义"""
import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List
from post_match_review.domain_types.analysis import AnalysisResult


@dataclass
class MatchSummary:
    """比赛摘要"""
    match_id: str
    duration: int
    radiant_win: bool
    radiant_score: int
    dire_score: int
    user_hero: str
    user_team_win: bool
    key_events: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return dataclasses.asdict(self)


@dataclass
class ReviewReport:
    """完整复盘报告"""
    match_id: str
    match_summary: MatchSummary
    phase_results: List[AnalysisResult] = field(default_factory=list)
    overall_score: float = 0.0
    overall_confidence: float = 0.0
    key_findings: List[str] = field(default_factory=list)
    improvement_areas: List[str] = field(default_factory=list)
    markdown_report: str = ""
    terminal_state: str = ""
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return dataclasses.asdict(self)
