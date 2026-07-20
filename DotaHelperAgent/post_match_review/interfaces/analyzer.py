"""分析器接口契约"""
from typing import Protocol

from post_match_review.types.analysis import AnalysisContext, AnalysisResult
from post_match_review.types.match_data import MatchData


class IReviewAnalyzer(Protocol):
    """复盘分析器接口"""

    @property
    def phase_name(self) -> str:
        """分析阶段名称"""
        ...

    async def analyze(
        self,
        match_data: MatchData,
        context: AnalysisContext,
    ) -> AnalysisResult:
        """执行分析

        Args:
            match_data: 结构化比赛数据
            context: 分析上下文（包含已有结论、预算等）

        Returns:
            AnalysisResult: 分析结果
        """
        ...

    def validate_result(self, result: AnalysisResult) -> bool:
        """验证分析结果是否有效

        Args:
            result: 待验证的分析结果

        Returns:
            bool: 结果是否有效
        """
        ...
