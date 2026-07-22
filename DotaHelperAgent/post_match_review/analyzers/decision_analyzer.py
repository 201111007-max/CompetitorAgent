"""决策点分析器"""
from typing import List, Dict, Optional

from post_match_review.analyzers.base import BaseLLMReviewAnalyzer
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.engines.prompt_builder import PromptBuilder
from post_match_review.domain_types.match_data import MatchData
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.analyzers.decision")


class DecisionAnalyzer(BaseLLMReviewAnalyzer):
    """决策点分析器

    分析 Roshan 时机、推塔节奏、团战发起/撤退等关键决策。
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        prompt_builder: Optional[PromptBuilder] = None,
    ) -> None:
        super().__init__(llm_client, prompt_builder)
        logger.info("决策点分析器初始化完成")

    @property
    def phase_name(self) -> str:
        return "decisions"

    def _format_domain_data(self, match_data: MatchData) -> str:
        """格式化决策领域数据为可读文本

        Args:
            match_data: 结构化比赛数据

        Returns:
            str: 格式化的决策数据文本
        """
        raw = match_data.raw_metadata or {}
        objectives = raw.get("objectives") or []
        logger.debug(
            "[%s] 格式化决策数据: duration=%d, radiant_win=%s, "
            "teamfight_count=%d, objectives_count=%d",
            self.phase_name,
            match_data.duration,
            match_data.radiant_win,
            len(match_data.teamfight_data) if match_data.teamfight_data else 0,
            len(objectives),
        )

        parts: List[str] = []
        parts.append("## 决策分析数据")
        parts.append("")

        # 比赛时间线与关键事件
        duration_min = match_data.duration // 60
        parts.append(f"### 比赛概况")
        parts.append(f"- 总时长: {duration_min} 分钟")
        parts.append(f"- 总击杀: {match_data.radiant_score + match_data.dire_score}")
        parts.append(f"- 胜利方: {'天辉' if match_data.radiant_win else '夜魇'}")
        parts.append("")

        # 团战时间线（作为决策点参考）
        if match_data.teamfight_data:
            parts.append("### 团战时间线（决策点参考）")
            for i, tf in enumerate(match_data.teamfight_data, 1):
                minutes = tf.start // 60
                seconds = tf.start % 60
                winner = "天辉" if tf.radiant_gold_delta > tf.dire_gold_delta else "夜魇"
                parts.append(
                    f"- 团战 {i} ({minutes}:{seconds:02d}): "
                    f"{tf.deaths} 死亡, 优势方 {winner} "
                    f"(经济差 {tf.radiant_gold_delta - tf.dire_gold_delta:+d})"
                )
            parts.append("")

        # 玩家表现摘要（用于评估决策质量）
        parts.append("### 玩家表现摘要")
        for player in match_data.players:
            if player.is_user:
                kda = f"{player.kills}/{player.deaths}/{player.assists}"
                parts.append(f"- **用户** ({player.hero_name}): KDA {kda}, GPM {player.gpm}")
                parts.append(f"  - 英雄伤害: {player.hero_damage}, 塔伤: {player.tower_damage}")
        parts.append("")

        # 原始元数据中的关键事件
        raw = match_data.raw_metadata
        if "objectives" in raw:
            parts.append("### 关键目标事件")
            for obj in raw["objectives"][:10]:
                obj_type = obj.get("type", "unknown")
                time_min = obj.get("time", 0) // 60
                parts.append(f"- {time_min} 分钟: {obj_type}")
            parts.append("")

        return "\n".join(parts)
