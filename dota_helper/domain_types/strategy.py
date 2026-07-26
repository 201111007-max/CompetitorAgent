"""分析策略类型定义"""
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class AnalysisStrategy:
    """分析策略"""
    match_type: str                   # 比赛类型分类
    priority_phases: List[str]        # 分析优先级排序
    budget_allocation: Dict[str, int] # 各阶段预算分配
    expected_depth: Dict[str, str]    # 各阶段预期分析深度
