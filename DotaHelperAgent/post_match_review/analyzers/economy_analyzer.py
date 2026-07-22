"""经济分析器"""
from typing import List, Dict, Optional

from post_match_review.analyzers.base import BaseLLMReviewAnalyzer
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.engines.prompt_builder import PromptBuilder
from post_match_review.domain_types.match_data import MatchData
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.analyzers.economy")


class EconomyAnalyzer(BaseLLMReviewAnalyzer):
    """经济分析器

    分析 GPM/XPM 曲线、装备购买效率、关键装备时间节点。
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        prompt_builder: Optional[PromptBuilder] = None,
    ) -> None:
        super().__init__(llm_client, prompt_builder)
        logger.info("经济分析器初始化完成")

    @property
    def phase_name(self) -> str:
        return "economy"

    def _format_domain_data(self, match_data: MatchData) -> str:
        """格式化经济领域数据为可读文本

        Args:
            match_data: 结构化比赛数据

        Returns:
            str: 格式化的经济数据文本
        """
        economy_data = match_data.economy_data
        if not economy_data:
            logger.warning(
                "[%s] 缺少 economy_data，返回空字符串",
                self.phase_name,
            )
            return ""

        user_account_id = next(
            (p.account_id for p in match_data.players if p.is_user and p.account_id),
            None,
        )
        logger.debug(
            "[%s] 格式化经济数据: players=%d, user_account_id=%s, "
            "gpm_series=%d, networth_series=%d, purchase_logs=%d",
            self.phase_name,
            len(match_data.players),
            user_account_id,
            len(economy_data.gpm_series),
            len(economy_data.networth_series),
            len(economy_data.purchase_log),
        )

        parts: List[str] = []
        parts.append("## 经济数据")
        parts.append("")

        player_map: Dict[str, str] = {}
        for player in match_data.players:
            if player.account_id:
                player_map[player.account_id] = player.hero_name

        # GPM/XPM 摘要
        parts.append("### GPM/XPM 摘要")
        for account_id, gpm_series in economy_data.gpm_series.items():
            hero_name = player_map.get(account_id, account_id)
            xpm_series = economy_data.xpm_series.get(account_id, [])
            avg_gpm = sum(gpm_series) // len(gpm_series) if gpm_series else 0
            avg_xpm = sum(xpm_series) // len(xpm_series) if xpm_series else 0
            peak_gpm = max(gpm_series) if gpm_series else 0
            marker = " **(用户)**" if account_id == user_account_id else ""
            parts.append(
                f"- {hero_name}{marker}: 平均 GPM {avg_gpm}, "
                f"平均 XPM {avg_xpm}, 峰值 GPM {peak_gpm}"
            )
        parts.append("")

        # 净经济曲线关键点
        if economy_data.networth_series:
            parts.append("### 净经济变化趋势")
            for account_id, nw_series in economy_data.networth_series.items():
                hero_name = player_map.get(account_id, account_id)
                if len(nw_series) >= 3:
                    early = nw_series[len(nw_series) // 4]
                    mid = nw_series[len(nw_series) // 2]
                    late = nw_series[-1]
                    parts.append(
                        f"- {hero_name}: 前期 {early}, 中期 {mid}, 后期 {late}"
                    )
            parts.append("")

        # 购买记录摘要
        if economy_data.purchase_log:
            parts.append("### 关键购买记录")
            for account_id, purchases in economy_data.purchase_log.items():
                hero_name = player_map.get(account_id, account_id)
                if purchases:
                    item_names = [p.get("key", p.get("name", "unknown")) for p in purchases[:5]]
                    parts.append(f"- {hero_name}: {', '.join(item_names)}")
            parts.append("")

        return "\n".join(parts)
