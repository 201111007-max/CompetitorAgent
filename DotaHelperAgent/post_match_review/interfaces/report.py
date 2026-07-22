"""报告构建器接口契约"""
from typing import List, Protocol

from post_match_review.domain_types.analysis import AnalysisResult
from post_match_review.domain_types.match_data import MatchData
from post_match_review.domain_types.report import ReviewReport


class IReportBuilder(Protocol):
    """复盘报告构建器接口"""

    def build(
        self,
        match_data: MatchData,
        phase_results: List[AnalysisResult],
        terminal_state: str,
    ) -> ReviewReport:
        """聚合各阶段分析结果生成完整复盘报告

        Args:
            match_data: 结构化比赛数据
            phase_results: 各阶段分析结果列表
            terminal_state: 复盘终态类型

        Returns:
            ReviewReport: 完整复盘报告
        """
        ...

    def cross_validate(
        self,
        phase_results: List[AnalysisResult],
    ) -> List[str]:
        """交叉验证各阶段结论的一致性

        Args:
            phase_results: 各阶段分析结果列表

        Returns:
            List[str]: 发现的矛盾或补充建议
        """
        ...
