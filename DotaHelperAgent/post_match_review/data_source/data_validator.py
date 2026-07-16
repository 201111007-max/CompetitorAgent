"""数据完整性校验"""
from typing import List, Tuple

from post_match_review.observability.logger import get_logger
from post_match_review.types.match_data import MatchData

logger = get_logger("data_source.data_validator")


class DataValidator:
    """比赛数据完整性校验器"""

    REQUIRED_FIELDS: List[str] = ["match_id", "duration", "players", "radiant_win"]
    MIN_PLAYERS: int = 10
    MIN_DURATION: int = 60

    def validate(self, match_data: MatchData) -> Tuple[bool, List[str]]:
        """校验结构化比赛数据是否完整

        Args:
            match_data: 待校验数据

        Returns:
            Tuple[bool, List[str]]: (是否通过, 错误原因列表)
        """
        errors: List[str] = []

        # 校验 match_id
        if not match_data.match_id:
            errors.append("match_id 为空")

        # 校验 duration
        if match_data.duration < self.MIN_DURATION:
            errors.append(
                f"比赛时长 {match_data.duration}s 低于最小值 {self.MIN_DURATION}s"
            )

        # 校验 players
        if len(match_data.players) < self.MIN_PLAYERS:
            errors.append(
                f"玩家数量 {len(match_data.players)} 低于最小值 {self.MIN_PLAYERS}"
            )

        # 校验 radiant_win 类型
        if not isinstance(match_data.radiant_win, bool):
            errors.append("radiant_win 类型错误，应为 bool")

        # 校验玩家数据完整性
        for i, player in enumerate(match_data.players):
            if player.hero_id <= 0:
                errors.append(f"玩家 {i} 的 hero_id 无效: {player.hero_id}")

        if errors:
            logger.warning("数据校验未通过: %s", errors)
            return False, errors

        logger.info("数据校验通过: match_id=%s", match_data.match_id)
        return True, []
