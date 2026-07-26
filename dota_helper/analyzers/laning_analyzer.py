"""对线期分析器

数据格式化已迁移到 YAML 声明（tactical_laning.yaml）+ DataFormatter。
_format_domain_data() 使用基类默认实现（返回空字符串）。
"""
from typing import Optional

from dota_helper.analyzers.base import BaseLLMReviewAnalyzer
from dota_helper.interfaces.llm import ILLMClient
from dota_helper.engines.prompt_builder import PromptBuilder
from dota_helper.observability.logger import get_logger

logger = get_logger("analyzers.laning")


class LaningAnalyzer(BaseLLMReviewAnalyzer):
    """对线期分析器

    分析 0-10 分钟的对线期表现，包括：
    - 补刀效率（last hits/denies）
    - 英雄消耗换血（hero damage）
    - 净经济差距（net worth delta）
    - 分路策略评估

    数据格式化由 YAML data_requirements 声明驱动，
    DataFormatter 自动处理 player_stats 和 player_lane 格式。
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
