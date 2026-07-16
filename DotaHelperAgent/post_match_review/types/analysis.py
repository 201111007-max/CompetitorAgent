"""分析相关类型定义"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class Conclusion:
    """分析结论"""
    phase: str
    finding: str
    confidence: float
    has_evidence: bool = False
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisStrategy:
    """分析策略"""
    target_phases: list[str] = field(default_factory=list)
    priority_phases: list[str] = field(default_factory=list)
    custom_parameters: Dict[str, Any] = field(default_factory=dict)
