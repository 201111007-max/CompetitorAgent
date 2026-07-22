"""视野分析器"""
from typing import List, Dict, Optional

from post_match_review.analyzers.base import BaseLLMReviewAnalyzer
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.engines.prompt_builder import PromptBuilder
from post_match_review.domain_types.analysis import AnalysisResult
from post_match_review.domain_types.match_data import MatchData
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.analyzers.vision")


class VisionAnalyzer(BaseLLMReviewAnalyzer):
    """视野分析器

    分析守卫放置热力图、关键视野盲区、反野效率。
    视野数据缺失时降低置信度并标注。
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        prompt_builder: Optional[PromptBuilder] = None,
    ) -> None:
        super().__init__(llm_client, prompt_builder)
        self._vision_data_available = True
        logger.info("视野分析器初始化完成")

    @property
    def phase_name(self) -> str:
        return "vision"

    def validate_result(self, result: AnalysisResult) -> bool:
        """验证分析结果（视野数据缺失时使用降级标准）

        当视野数据不可用时，降低验证标准：
        - 置信度阈值从 0.6 降至 0.4
        - 只要有结论即可通过验证

        Args:
            result: 待验证的分析结果

        Returns:
            bool: 结果是否有效
        """
        # 视野数据缺失时降低验证标准
        if not self._vision_data_available:
            is_valid = result.confidence >= 0.4 and len(result.conclusions) > 0
            logger.info(
                "[阶段:%s] 视野数据缺失，使用降级验证标准: valid=%s, "
                "confidence=%.2f, conclusions=%d",
                self.phase_name,
                is_valid,
                result.confidence,
                len(result.conclusions),
            )
            return is_valid
        return super().validate_result(result)

    def _format_domain_data(self, match_data: MatchData) -> str:
        """格式化视野领域数据为可读文本

        Args:
            match_data: 结构化比赛数据

        Returns:
            str: 格式化的视野数据文本
        """
        parts: List[str] = []
        parts.append("## 视野数据")
        parts.append("")

        raw = match_data.raw_metadata

        # 检查视野数据是否可用
        vision_data = raw.get("vision", {})
        if not vision_data:
            self._vision_data_available = False
            logger.warning(
                "[阶段:%s] 视野数据不可用，分析将基于推断",
                self.phase_name,
            )
            parts.append("> **注意**: 视野数据不可用，分析将基于推断和有限信息。")
            parts.append("")
            # 提供有限的视野相关信息
            parts.append("### 可用信息")
            parts.append(f"- 比赛时长: {match_data.duration // 60} 分钟")
            parts.append(f"- 游戏模式: {match_data.game_mode}")
            parts.append("")
            return "\n".join(parts)

        self._vision_data_available = True
        obs_data = vision_data.get("obs", {})
        sen_data = vision_data.get("sen", {})
        obs_count = sum(len(v) if isinstance(v, list) else v for v in obs_data.values())
        sen_count = sum(len(v) if isinstance(v, list) else v for v in sen_data.values())
        logger.debug(
            "[阶段:%s] 格式化视野数据: obs_count=%d, sen_count=%d",
            self.phase_name,
            obs_count,
            sen_count,
        )

        # 守卫放置数据
        if "obs" in vision_data:
            parts.append("### 守卫放置（Observer）")
            obs_data = vision_data["obs"]
            if isinstance(obs_data, dict):
                for account_id, placements in obs_data.items():
                    if isinstance(placements, list):
                        parts.append(f"- 玩家 {account_id}: {len(placements)} 个守卫")
                    elif isinstance(placements, int):
                        parts.append(f"- 玩家 {account_id}: {placements} 个守卫")
            parts.append("")

        if "sen" in vision_data:
            parts.append("### 守卫放置（Sentry）")
            sen_data = vision_data["sen"]
            if isinstance(sen_data, dict):
                for account_id, placements in sen_data.items():
                    if isinstance(placements, list):
                        parts.append(f"- 玩家 {account_id}: {len(placements)} 个真眼")
                    elif isinstance(placements, int):
                        parts.append(f"- 玩家 {account_id}: {placements} 个真眼")
            parts.append("")

        # 反野效率相关
        if "life_state" in raw:
            parts.append("### 生命状态数据")
            parts.append(f"- 数据点数量: {len(raw['life_state'])}")
            parts.append("")

        return "\n".join(parts)
