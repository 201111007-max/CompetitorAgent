"""
反馈采集器 - 采集显式和隐式反馈

职责：
- 采集显式反馈（用户打分）
- 采集隐式反馈（行为推断）
- 生成 FeedbackRecord 并存储
- 可选：上报反馈到 Langfuse
"""

import time
import uuid
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import logging

from feedback.store import FeedbackStore, FeedbackRecord

logger = logging.getLogger(__name__)

# Langfuse 可选导入
try:
    from utils.langfuse_adapter import LangfuseClient
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    LangfuseClient = None


@dataclass
class ImplicitFeedbackConfig:
    """隐式反馈配置"""
    adopt_score: float = 1.0
    partial_adopt_score: float = 0.5
    ignore_score: float = -0.2
    ignore_timeout: int = 180  # 秒
    reverse_score: float = -0.5


class FeedbackCollector:
    """反馈采集器"""

    def __init__(
        self,
        store: FeedbackStore,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        初始化反馈采集器

        Args:
            store: 反馈存储实例
            config: 配置字典
        """
        self.store = store
        self.config = config or {}

        # 隐式反馈配置
        implicit_config = self.config.get("implicit", {})
        self.implicit_config = ImplicitFeedbackConfig(
            adopt_score=implicit_config.get("adopt_score", 1.0),
            partial_adopt_score=implicit_config.get("partial_adopt_score", 0.5),
            ignore_score=implicit_config.get("ignore_score", -0.2),
            ignore_timeout=implicit_config.get("ignore_timeout", 180),
            reverse_score=implicit_config.get("reverse_score", -0.5),
        )

        # 推荐记录缓存（recommendation_id -> 推荐上下文）
        self._recommendation_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_max_size = 1000

        logger.info("反馈采集器初始化完成")

    def collect_explicit_feedback(
        self,
        recommendation_id: str,
        score: float,
        comment: Optional[str] = None
    ) -> Optional[FeedbackRecord]:
        """
        采集显式反馈

        Args:
            recommendation_id: 推荐 ID
            score: 评分（1-5）
            comment: 可选文字备注

        Returns:
            生成的反馈记录，如果推荐 ID 不存在返回 None
        """
        # 从缓存获取推荐上下文
        rec_context = self._recommendation_cache.get(recommendation_id)
        if not rec_context:
            logger.warning(f"推荐 ID 不存在: {recommendation_id}")
            return None

        # 归一化评分到 [-1, 1] 范围
        normalized_score = (score - 3) / 2  # 1->-1, 3->0, 5->1

        record = FeedbackRecord(
            feedback_id=str(uuid.uuid4()),
            recommendation_id=recommendation_id,
            feedback_type="explicit",
            score=normalized_score,
            engine=rec_context.get("engine", ""),
            event_type=rec_context.get("event_type", ""),
            rule_name=rec_context.get("rule_name"),
            context=rec_context,
            timestamp=time.time(),
            metadata={"comment": comment} if comment else {}
        )

        self.store.save(record)
        logger.info(f"采集显式反馈: rec_id={recommendation_id}, score={score}")

        # 上报到 Langfuse（可选）
        self._report_to_langfuse(record)

        return record

    def collect_implicit_feedback(
        self,
        recommendation_id: str,
        behavior_type: str
    ) -> Optional[FeedbackRecord]:
        """
        采集隐式反馈

        Args:
            recommendation_id: 推荐 ID
            behavior_type: 行为类型 ("adopt" | "partial_adopt" | "ignore" | "reverse")

        Returns:
            生成的反馈记录，如果推荐 ID 不存在返回 None
        """
        # 从缓存获取推荐上下文
        rec_context = self._recommendation_cache.get(recommendation_id)
        if not rec_context:
            logger.warning(f"推荐 ID 不存在: {recommendation_id}")
            return None

        # 根据行为类型映射评分
        score_map = {
            "adopt": self.implicit_config.adopt_score,
            "partial_adopt": self.implicit_config.partial_adopt_score,
            "ignore": self.implicit_config.ignore_score,
            "reverse": self.implicit_config.reverse_score,
        }

        score = score_map.get(behavior_type, 0.0)

        record = FeedbackRecord(
            feedback_id=str(uuid.uuid4()),
            recommendation_id=recommendation_id,
            feedback_type="implicit",
            score=score,
            engine=rec_context.get("engine", ""),
            event_type=rec_context.get("event_type", ""),
            rule_name=rec_context.get("rule_name"),
            context=rec_context,
            timestamp=time.time(),
            metadata={"behavior_type": behavior_type}
        )

        self.store.save(record)
        logger.info(f"采集隐式反馈: rec_id={recommendation_id}, behavior={behavior_type}")

        # 上报到 Langfuse（可选）
        self._report_to_langfuse(record)

        return record

    def record_recommendation(
        self,
        recommendation_id: str,
        engine: str,
        event_type: str,
        rule_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        记录推荐上下文（供后续反馈关联）

        Args:
            recommendation_id: 推荐 ID
            engine: 产生推荐的引擎
            event_type: 触发推荐的事件类型
            rule_name: 关联的规则名称（如有）
            context: 推荐上下文
        """
        # 缓存满时清理旧数据
        if len(self._recommendation_cache) >= self._cache_max_size:
            self._cleanup_cache()

        self._recommendation_cache[recommendation_id] = {
            "recommendation_id": recommendation_id,
            "engine": engine,
            "event_type": event_type,
            "rule_name": rule_name,
            "context": context or {},
            "recorded_at": time.time()
        }

        logger.debug(f"记录推荐上下文: {recommendation_id}")

    def _cleanup_cache(self) -> None:
        """清理缓存（移除最旧的记录）"""
        if not self._recommendation_cache:
            return

        # 按时间排序，移除最旧的一半
        sorted_items = sorted(
            self._recommendation_cache.items(),
            key=lambda x: x[1].get("recorded_at", 0)
        )

        remove_count = len(sorted_items) // 2
        for i in range(remove_count):
            del self._recommendation_cache[sorted_items[i][0]]

        logger.debug(f"清理推荐缓存: 移除 {remove_count} 条")

    def _report_to_langfuse(self, record: FeedbackRecord) -> None:
        """
        上报反馈到 Langfuse（可选）

        Args:
            record: 反馈记录
        """
        if not LANGFUSE_AVAILABLE:
            return

        try:
            langfuse_client = LangfuseClient.get_instance()
            if not langfuse_client.enabled:
                return

            # 创建 Langfuse Score
            score_name = self.config.get("langfuse", {}).get("score_name", "user_feedback")
            langfuse_client.score(
                name=score_name,
                value=record.score,
                comment=f"feedback_id={record.feedback_id}, engine={record.engine}, event_type={record.event_type}"
            )
            logger.debug(f"反馈已上报到 Langfuse: {record.feedback_id}")

        except Exception as e:
            # Langfuse 上报失败不影响主流程
            logger.debug(f"Langfuse 上报失败（非致命错误）: {e}")
