"""分析相关类型定义"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

from post_match_review.interfaces.budget import IIterationBudget


@dataclass
class Conclusion:
    """单条分析结论"""
    title: str
    content: str
    evidence: List[str] = field(default_factory=list)
    has_evidence: bool = False
    impact: str = "medium"  # high/medium/low
    suggestion: Optional[str] = None


@dataclass
class AnalysisResult:
    """单个分析阶段的结果"""
    phase: str
    conclusions: List[Conclusion] = field(default_factory=list)
    confidence: float = 0.0
    iterations_used: int = 0
    tokens_consumed: int = 0
    analysis_text: str = ""


@dataclass
class AnalysisContext:
    """分析上下文"""
    phase: str
    budget: IIterationBudget
    completed_results: List[AnalysisResult] = field(default_factory=list)
    iteration_feedback: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    messages: List[Dict[str, str]] = field(default_factory=list)



