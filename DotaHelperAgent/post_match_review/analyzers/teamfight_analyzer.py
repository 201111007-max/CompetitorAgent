"""团战分析器"""
from typing import List, Dict, Optional

from post_match_review.analyzers.base import BaseLLMReviewAnalyzer
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.engines.prompt_builder import PromptBuilder
from post_match_review.domain_types.match_data import MatchData
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.analyzers.teamfight")


class TeamfightAnalyzer(BaseLLMReviewAnalyzer):
    """团战分析器

    分析团战参与率、技能释放时机、走位站位等。
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        prompt_builder: Optional[PromptBuilder] = None,
    ) -> None:
        super().__init__(llm_client, prompt_builder)
        logger.info("团战分析器初始化完成")

    @property
    def phase_name(self) -> str:
        return "teamfight"

    def _format_domain_data(self, match_data: MatchData) -> str:
        """格式化团战领域数据为可读文本

        Args:
            match_data: 结构化比赛数据

        Returns:
            str: 格式化的团战数据文本
        """
        teamfights = match_data.teamfight_data
        if not teamfights:
            logger.warning(
                "[%s] 缺少 teamfight_data，返回空字符串",
                self.phase_name,
            )
            return ""
        total_deaths = sum(tf.deaths for tf in teamfights)
        radiant_total_delta = sum(tf.radiant_gold_delta for tf in teamfights)
        logger.debug(
            "[阶段:%s] 格式化团战数据: count=%d, total_deaths=%d, "
            "radiant_total_delta=%+d",
            self.phase_name,
            len(teamfights),
            total_deaths,
            radiant_total_delta,
        )

        parts: List[str] = []
        parts.append("## 团战数据")
        parts.append("")

        player_map: Dict[str, str] = {}
        for player in match_data.players:
            if player.account_id:
                player_map[player.account_id] = player.hero_name

        for i, tf in enumerate(teamfights, 1):
            minutes = tf.start // 60
            seconds = tf.start % 60
            duration = tf.end - tf.start
            parts.append(f"### 团战 {i} ({minutes}:{seconds:02d}, 持续 {duration}s)")
            parts.append(f"- 死亡人数: {tf.deaths}")
            parts.append(f"- 天辉经济变化: {tf.radiant_gold_delta:+d}")
            parts.append(f"- 夜魇经济变化: {tf.dire_gold_delta:+d}")
            participants = [player_map.get(pid, pid) for pid in tf.players[:6]]
            parts.append(f"- 参与英雄: {', '.join(participants)}")
            parts.append("")

        # 汇总统计
        total_fights = len(teamfights)
        total_deaths = sum(tf.deaths for tf in teamfights)
        radiant_total_delta = sum(tf.radiant_gold_delta for tf in teamfights)
        parts.append("### 团战汇总")
        parts.append(f"- 总团战次数: {total_fights}")
        parts.append(f"- 总死亡人数: {total_deaths}")
        parts.append(f"- 天辉团战总经济变化: {radiant_total_delta:+d}")
        parts.append("")

        return "\n".join(parts)
