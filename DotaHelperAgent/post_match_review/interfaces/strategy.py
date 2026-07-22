"""战略循环接口契约"""
from typing import Any, Dict, List, Protocol

from post_match_review.domain_types.match_data import MatchData
from post_match_review.domain_types.strategy import AnalysisStrategy


class IStrategicLoop(Protocol):
    """战略循环接口"""

    def evaluate(self, match_data: MatchData) -> AnalysisStrategy:
        """评估比赛并制定分析策略

        Args:
            match_data: 结构化比赛数据

        Returns:
            AnalysisStrategy: 分析策略
        """
        ...

    def classify_match(self, match_data: MatchData) -> str:
        """分类比赛类型

        Args:
            match_data: 结构化比赛数据

        Returns:
            str: 比赛类型枚举值
        """
        ...

    def allocate_budget(self, match_type: str) -> Dict[str, int]:
        """为各分析阶段分配预算

        Args:
            match_type: 比赛类型

        Returns:
            Dict[str, int]: 阶段 -> 迭代次数
        """
        ...
