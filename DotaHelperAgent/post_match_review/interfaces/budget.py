"""迭代预算接口"""
from typing import Protocol
from post_match_review.types.enums import BudgetDecision


class IIterationBudget(Protocol):
    """迭代预算控制接口"""

    def consume(self, delta_tokens: int = 0) -> BudgetDecision:
        """消费一个迭代配额

        Args:
            delta_tokens: 本轮消耗的 token 数

        Returns:
            BudgetDecision: 预算决策（继续/停止/递减）
        """
        ...

    def refund(self) -> None:
        """退还一个迭代配额"""
        ...

    @property
    def remaining_iterations(self) -> int:
        """剩余迭代次数"""
        ...

    @property
    def remaining_tokens(self) -> int:
        """剩余 token 配额"""
        ...
