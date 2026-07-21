"""迭代预算控制器单元测试"""
import pytest
from post_match_review.engines.budget import IterationBudget
from post_match_review.domain_types.enums import BudgetDecision


class TestIterationBudget:
    """测试迭代预算控制器"""

    def test_init_default_values(self) -> None:
        """测试初始化默认值"""
        budget = IterationBudget(max_iterations=15, max_tokens=100000)
        assert budget.remaining_iterations == 15
        assert budget.remaining_tokens == 100000

    def test_consume_returns_continue_when_budget_available(self) -> None:
        """测试有预算时返回 CONTINUE"""
        budget = IterationBudget(max_iterations=15, max_tokens=100000)
        decision = budget.consume(delta_tokens=1000)
        assert decision == BudgetDecision.CONTINUE
        assert budget.remaining_iterations == 14
        assert budget.remaining_tokens == 99000

    def test_consume_returns_stop_budget_used_when_iterations_exhausted(self) -> None:
        """测试迭代次数耗尽时返回 STOP_BUDGET_USED"""
        budget = IterationBudget(max_iterations=2, max_tokens=100000)
        budget.consume(delta_tokens=1000)
        budget.consume(delta_tokens=1000)
        decision = budget.consume(delta_tokens=1000)
        assert decision == BudgetDecision.STOP_BUDGET_USED

    def test_consume_returns_stop_token_limit_when_token_threshold_reached(self) -> None:
        """测试 Token 达到 90% 阈值时返回 STOP_TOKEN_LIMIT"""
        budget = IterationBudget(max_iterations=15, max_tokens=10000)
        # 消耗 9000 tokens (90%)
        budget.consume(delta_tokens=9000)
        decision = budget.consume(delta_tokens=1000)
        assert decision == BudgetDecision.STOP_TOKEN_LIMIT

    def test_consume_returns_stop_diminishing_when_marginal_decrease_detected(self) -> None:
        """测试边际递减检测"""
        budget = IterationBudget(
            max_iterations=15,
            max_tokens=100000,
            diminishing_threshold=500,
            min_continuations=3,
        )
        # 前 3 次迭代必须继续
        budget.consume(delta_tokens=1000)
        budget.consume(delta_tokens=1000)
        budget.consume(delta_tokens=1000)
        # 连续 2 次增量 < 500
        budget.consume(delta_tokens=400)
        budget.consume(delta_tokens=300)
        decision = budget.consume(delta_tokens=200)
        assert decision == BudgetDecision.STOP_DIMINISHING

    def test_refund_restores_iteration(self) -> None:
        """测试退还配额"""
        budget = IterationBudget(max_iterations=10, max_tokens=100000)
        budget.consume(delta_tokens=1000)
        budget.consume(delta_tokens=1000)
        assert budget.remaining_iterations == 8
        budget.refund()
        assert budget.remaining_iterations == 9

    def test_refund_does_not_exceed_max(self) -> None:
        """测试退还不会超过最大迭代次数"""
        budget = IterationBudget(max_iterations=10, max_tokens=100000)
        budget.refund()
        assert budget.remaining_iterations == 10

    def test_token_tracking_across_multiple_consumes(self) -> None:
        """测试多次消费的 Token 累计"""
        budget = IterationBudget(max_iterations=15, max_tokens=100000)
        budget.consume(delta_tokens=1000)
        budget.consume(delta_tokens=2000)
        budget.consume(delta_tokens=3000)
        assert budget.remaining_tokens == 94000

    def test_diminishing_detection_resets_after_high_delta(self) -> None:
        """测试高增量后重置递减计数"""
        budget = IterationBudget(
            max_iterations=15,
            max_tokens=100000,
            diminishing_threshold=500,
            min_continuations=3,
        )
        # 3 次必须继续
        budget.consume(delta_tokens=1000)
        budget.consume(delta_tokens=1000)
        budget.consume(delta_tokens=1000)
        # 低增量
        budget.consume(delta_tokens=400)
        # 高增量，重置计数
        budget.consume(delta_tokens=1000)
        # 低增量，但计数已重置
        budget.consume(delta_tokens=400)
        decision = budget.consume(delta_tokens=300)
        # 应该继续，因为计数被重置了
        assert decision == BudgetDecision.CONTINUE

    def test_concurrent_access_thread_safety(self) -> None:
        """测试线程安全"""
        import threading
        budget = IterationBudget(
            max_iterations=100,
            max_tokens=1000000,
            diminishing_threshold=0,  # 禁用边际递减
        )
        
        def consume_multiple():
            for _ in range(10):
                budget.consume(delta_tokens=100)
        
        threads = [threading.Thread(target=consume_multiple) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # 50 次消费
        assert budget.remaining_iterations == 50
        assert budget.remaining_tokens == 995000
