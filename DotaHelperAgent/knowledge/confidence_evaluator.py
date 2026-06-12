"""置信度评估 - 根据数据源可信度评估知识质量"""

from typing import Dict, Any
from utils.log_config import get_logger

logger = get_logger("confidence_evaluator", component="knowledge")


class ConfidenceEvaluator:
    """置信度评估器

    功能：
    - 根据数据源可信度评估知识质量
    - 结合元数据（胜率、选取率等）调整置信度
    - 提供置信度分数（0-1）
    """

    def __init__(self):
        """初始化置信度评估器"""
        # 数据源可信度映射
        self.source_confidence = {
            "opendota": 0.9,      # OpenDota API 数据
            "dotabuff": 0.85,     # Dotabuff 数据
            "wiki": 0.7,          # 官方 Wiki
            "guide": 0.6,         # 攻略文章
            "user": 0.5,          # 用户贡献
            "unknown": 0.3        # 未知来源
        }

        logger.info("置信度评估器初始化完成")

    def evaluate(
        self,
        knowledge: Dict[str, Any]
    ) -> float:
        """评估知识置信度

        Args:
            knowledge: 知识字典

        Returns:
            置信度分数（0-1）
        """
        # 基础置信度（基于数据源）
        source = knowledge.get("source", "unknown")
        base_confidence = self.source_confidence.get(source, 0.3)

        # 应用元数据调整
        confidence = base_confidence

        # 胜率调整
        win_rate = knowledge.get("win_rate")
        if win_rate is not None:
            confidence = self._adjust_by_win_rate(confidence, win_rate)

        # 选取率调整
        pick_rate = knowledge.get("pick_rate")
        if pick_rate is not None:
            confidence = self._adjust_by_pick_rate(confidence, pick_rate)

        # 时效性调整
        timestamp = knowledge.get("timestamp")
        if timestamp is not None:
            confidence = self._adjust_by_recency(confidence, timestamp)

        # 确保置信度在 0-1 范围内
        confidence = max(0.0, min(1.0, confidence))

        logger.debug(f"知识置信度评估: source={source}, base={base_confidence:.2f}, final={confidence:.2f}")

        return confidence

    def _adjust_by_win_rate(
        self,
        confidence: float,
        win_rate: float
    ) -> float:
        """根据胜率调整置信度

        Args:
            confidence: 当前置信度
            win_rate: 胜率（0-1）

        Returns:
            调整后的置信度
        """
        # 高胜率（>60%）提升置信度
        if win_rate > 0.6:
            boost = (win_rate - 0.6) * 0.5  # 最多提升 0.2
            confidence += boost
        # 低胜率（<45%）降低置信度
        elif win_rate < 0.45:
            penalty = (0.45 - win_rate) * 0.3  # 最多降低 0.135
            confidence -= penalty

        return confidence

    def _adjust_by_pick_rate(
        self,
        confidence: float,
        pick_rate: float
    ) -> float:
        """根据选取率调整置信度

        Args:
            confidence: 当前置信度
            pick_rate: 选取率（0-1）

        Returns:
            调整后的置信度
        """
        # 高选取率（>50%）提升置信度
        if pick_rate > 0.5:
            boost = (pick_rate - 0.5) * 0.2  # 最多提升 0.1
            confidence += boost
        # 低选取率（<20%）降低置信度
        elif pick_rate < 0.2:
            penalty = (0.2 - pick_rate) * 0.5  # 最多降低 0.1
            confidence -= penalty

        return confidence

    def _adjust_by_recency(
        self,
        confidence: float,
        timestamp: int
    ) -> float:
        """根据时效性调整置信度

        Args:
            confidence: 当前置信度
            timestamp: 知识的时间戳

        Returns:
            调整后的置信度
        """
        import time

        # 计算知识年龄（秒）
        current_time = int(time.time())
        age_seconds = current_time - timestamp
        age_days = age_seconds / (24 * 60 * 60)

        # 根据年龄降低置信度
        if age_days > 30:  # 超过30天
            penalty = min(0.3, (age_days - 30) / 365 * 0.3)  # 最多降低0.3
            confidence -= penalty

        return confidence

    def get_source_confidence(self, source: str) -> float:
        """获取数据源的基础置信度

        Args:
            source: 数据源名称

        Returns:
            基础置信度
        """
        return self.source_confidence.get(source, 0.3)

    def add_source(self, source: str, confidence: float) -> None:
        """添加新的数据源

        Args:
            source: 数据源名称
            confidence: 置信度（0-1）
        """
        if not 0 <= confidence <= 1:
            raise ValueError(f"置信度必须在 0-1 范围内: {confidence}")

        self.source_confidence[source] = confidence
        logger.info(f"添加数据源: {source}, 置信度: {confidence}")

    def evaluate_batch(
        self,
        knowledge_list: list
    ) -> list:
        """批量评估知识置信度

        Args:
            knowledge_list: 知识列表

        Returns:
            带置信度的知识列表
        """
        for knowledge in knowledge_list:
            knowledge["confidence"] = self.evaluate(knowledge)

        # 按置信度排序
        knowledge_list.sort(key=lambda x: x.get("confidence", 0), reverse=True)

        return knowledge_list
