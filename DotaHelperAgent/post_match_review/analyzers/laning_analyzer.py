"""对线期分析器"""
from typing import List, Dict, Optional

from post_match_review.analyzers.base import BaseLLMReviewAnalyzer
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.engines.prompt_builder import PromptBuilder
from post_match_review.domain_types.match_data import MatchData
from post_match_review.observability.logger import get_logger

logger = get_logger("analyzers.laning")


class LaningAnalyzer(BaseLLMReviewAnalyzer):
    """对线期分析器

    分析 0-10 分钟的对线期表现，包括：
    - 补刀效率（last hits/denies）
    - 英雄消耗换血（hero damage）
    - 净经济差距（net worth delta）
    - 神符利用率（如果有数据）
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        prompt_builder: Optional[PromptBuilder] = None,
    ) -> None:
        """初始化对线期分析器

        Args:
            llm_client: LLM 客户端实例
            prompt_builder: 提示词构建器，默认使用内置构建器
        """
        super().__init__(llm_client, prompt_builder)
        logger.info("对线期分析器初始化完成")

    @property
    def phase_name(self) -> str:
        """分析阶段名称"""
        return "laning"

    def _format_domain_data(self, match_data: MatchData) -> str:
        """格式化对线期领域数据为可读文本

        Args:
            match_data: 结构化比赛数据

        Returns:
            str: 格式化的对线期数据文本
        """
        lane_data = match_data.lane_data
        if not lane_data:
            logger.warning(
                "[%s] 缺少 lane_data，返回空字符串",
                self.phase_name,
            )
            return ""

        logger.debug(
            "[%s] 格式化对线期数据: players=%d, lh_entries=%d, "
            "deny_entries=%d, networth_entries=%d, lane_entries=%d",
            self.phase_name,
            len(match_data.players),
            len(lane_data.lh_at_10),
            len(lane_data.denies_at_10),
            len(lane_data.networth_at_10),
            len(lane_data.player_lane),
        )

        parts: List[str] = []
        parts.append("## 对线期数据（0-10 分钟）")
        parts.append("")

        # 构建玩家 ID 到名称的映射
        player_map: Dict[str, str] = {}
        for player in match_data.players:
            if player.account_id:
                player_map[player.account_id] = player.hero_name

        # 10 分钟补刀数据
        parts.append("### 10 分钟补刀数")
        for account_id, lh in lane_data.lh_at_10.items():
            hero_name = player_map.get(account_id, account_id)
            denies = lane_data.denies_at_10.get(account_id, 0)
            parts.append(f"- {hero_name}: 补刀 {lh}, 反补 {denies}")
        parts.append("")

        # 10 分钟英雄伤害
        parts.append("### 10 分钟英雄伤害")
        for account_id, damage in lane_data.hero_damage_at_10.items():
            hero_name = player_map.get(account_id, account_id)
            parts.append(f"- {hero_name}: {damage} 伤害")
        parts.append("")

        # 10 分钟净经济
        parts.append("### 10 分钟净经济")
        for account_id, networth in lane_data.networth_at_10.items():
            hero_name = player_map.get(account_id, account_id)
            parts.append(f"- {hero_name}: {networth} 金币")
        parts.append("")

        # 分路信息
        if lane_data.player_lane:
            parts.append("### 分路分配")
            for account_id, lane in lane_data.player_lane.items():
                hero_name = player_map.get(account_id, account_id)
                lane_name = self._get_lane_name(lane)
                parts.append(f"- {hero_name}: {lane_name}")
            parts.append("")

        return "\n".join(parts)

    def _get_lane_name(self, lane: int) -> str:
        """将分路编号转换为名称

        Args:
            lane: 分路编号 (1-5)

        Returns:
            str: 分路名称
        """
        lane_names = {
            1: "安全路（优势路）",
            2: "中路",
            3: "劣势路",
            4: "野区辅助",
            5: "游走辅助",
        }
        return lane_names.get(lane, f"未知分路 ({lane})")
