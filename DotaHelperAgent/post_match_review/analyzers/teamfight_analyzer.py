"""团战分析器

列表遍历部分已迁移到 YAML 声明（tactical_teamfight.yaml）+ DataFormatter。
_format_domain_data() 仅保留汇总统计逻辑（无法声明化）。
"""
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
    团战列表遍历由 DataFormatter 处理（format: list_items），
    汇总统计逻辑保留在 Python 中（无法声明化）。
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
        """格式化团战汇总统计（列表遍历由 DataFormatter 处理）

        仅输出无法声明化的汇总统计信息。

        Args:
            match_data: 结构化比赛数据

        Returns:
            str: 格式化的团战汇总统计文本
        """
        teamfights = match_data.teamfight_data
        if not teamfights:
            logger.warning(
                "[%s] 缺少 teamfight_data，返回空字符串",
                self.phase_name,
            )
            return ""

        # 汇总统计（无法声明化，保留 Python 计算）
        total_fights = len(teamfights)
        total_deaths = sum(tf.deaths for tf in teamfights)
        radiant_total_delta = sum(tf.radiant_gold_delta for tf in teamfights)
        logger.debug(
            "[阶段:%s] 格式化团战汇总: count=%d, total_deaths=%d, "
            "radiant_total_delta=%+d",
            self.phase_name,
            total_fights,
            total_deaths,
            radiant_total_delta,
        )

        parts: List[str] = []
        parts.append("### 团战汇总")
        parts.append(f"- 总团战次数: {total_fights}")
        parts.append(f"- 总死亡人数: {total_deaths}")
        parts.append(f"- 天辉团战总经济变化: {radiant_total_delta:+d}")
        parts.append("")

        return "\n".join(parts)
