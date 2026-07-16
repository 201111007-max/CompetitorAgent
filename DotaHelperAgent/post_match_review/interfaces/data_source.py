"""数据源接口定义"""
from typing import Protocol
from post_match_review.types.match_data import MatchData


class IMatchDataSource(Protocol):
    """比赛数据源接口"""

    async def fetch_match(self, match_id: str) -> MatchData:
        """获取并返回结构化比赛数据

        Args:
            match_id: OpenDota 比赛 ID

        Returns:
            MatchData: 结构化比赛数据

        Raises:
            DataSourceError: 数据获取失败或校验不通过
        """
        ...
