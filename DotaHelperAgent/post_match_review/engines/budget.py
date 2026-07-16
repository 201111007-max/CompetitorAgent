"""迭代预算控制器（令牌桶 + 边际递减）"""
from threading import Lock
from post_match_review.interfaces.budget import IIterationBudget
from post_match_review.types.enums import BudgetDecision
from post_match_review.observability.logger import get_logger

logger = get_logger("engines.budget")


class IterationBudget(IIterationBudget):
    """迭代预算控制器（令牌桶 + 边际递减）"""

    def __init__(
        self,
        max_iterations: int,
        max_tokens: int,
        completion_threshold: float = 0.9,
        diminishing_threshold: int = 500,
        min_continuations: int = 3,
    ) -> None:
        """初始化预算控制器

        Args:
            max_iterations: 最大迭代次数
            max_tokens: 最大 Token 消耗
            completion_threshold: Token 完成阈值（0.9 表示 90%）
            diminishing_threshold: 边际递减阈值（连续增量低于此值判定递减）
            min_continuations: 最小继续次数（边际递减检测前的最小迭代次数）
        """
        self._max_iterations = max_iterations
        self._max_tokens = max_tokens
        self._completion_threshold = completion_threshold
        self._diminishing_threshold = diminishing_threshold
        self._min_continuations = min_continuations
        
        self._used_iterations = 0
        self._used_tokens = 0
        self._recent_deltas: list[int] = []
        self._lock = Lock()
        
        logger.info(
            "预算控制器初始化: max_iterations=%d, max_tokens=%d",
            max_iterations,
            max_tokens,
        )

    def consume(self, delta_tokens: int = 0) -> BudgetDecision:
        """消费一个迭代配额

        Args:
            delta_tokens: 本轮消耗的 token 数

        Returns:
            BudgetDecision: 预算决策（继续/停止/递减）
        """
        with self._lock:
            # 检查迭代次数是否耗尽
            if self._used_iterations >= self._max_iterations:
                logger.warning("迭代次数耗尽: %d/%d", self._used_iterations, self._max_iterations)
                return BudgetDecision.STOP_BUDGET_USED
            
            # 检查 Token 是否达到阈值
            token_threshold = int(self._max_tokens * self._completion_threshold)
            if self._used_tokens >= token_threshold:
                logger.warning(
                    "Token 达到阈值: %d/%d (%.1f%%)",
                    self._used_tokens,
                    token_threshold,
                    self._completion_threshold * 100,
                )
                return BudgetDecision.STOP_TOKEN_LIMIT
            
            # 检查边际递减（在最小继续次数之后）
            if self._used_iterations >= self._min_continuations:
                if self._check_diminishing(delta_tokens):
                    logger.info(
                        "检测到边际递减: 最近增量 %s < %d",
                        self._recent_deltas,
                        self._diminishing_threshold,
                    )
                    return BudgetDecision.STOP_DIMINISHING
            
            # 记录本次消费
            self._used_iterations += 1
            self._used_tokens += delta_tokens
            self._recent_deltas.append(delta_tokens)
            
            # 保持最近 2 个增量记录
            if len(self._recent_deltas) > 2:
                self._recent_deltas.pop(0)
            
            logger.debug(
                "消费预算: iteration=%d/%d, tokens=%d/%d",
                self._used_iterations,
                self._max_iterations,
                self._used_tokens,
                self._max_tokens,
            )
            
            return BudgetDecision.CONTINUE

    def _check_diminishing(self, current_delta: int) -> bool:
        """检查是否出现边际递减

        Args:
            current_delta: 当前增量

        Returns:
            bool: 是否递减
        """
        # 需要至少 2 个历史记录
        if len(self._recent_deltas) < 2:
            return False
        
        # 检查最近 2 次增量是否都低于阈值
        recent = self._recent_deltas[-2:]
        return all(delta < self._diminishing_threshold for delta in recent) and \
               current_delta < self._diminishing_threshold

    def refund(self) -> None:
        """退还一个迭代配额"""
        with self._lock:
            if self._used_iterations > 0:
                self._used_iterations -= 1
                logger.info("退还配额: 剩余迭代 %d", self._used_iterations)

    @property
    def remaining_iterations(self) -> int:
        """剩余迭代次数"""
        return self._max_iterations - self._used_iterations

    @property
    def remaining_tokens(self) -> int:
        """剩余 token 配额"""
        return self._max_tokens - self._used_tokens
