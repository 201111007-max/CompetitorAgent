"""core/budget.py + budget_controller.py 单测：终止分支（成本条件已移除）"""

from concurrent.futures import ThreadPoolExecutor

from competitor_agent.core.budget import IterationBudget
from competitor_agent.core.budget_controller import BudgetController, StopReason
from competitor_agent.domain_types import GapStatus, InfoGap


def _gap(field="pricing", priority=5, confidence=0.0, status=GapStatus.OPEN):
    return InfoGap(field=field, priority=priority, confidence=confidence, status=status)


class TestIterationBudget:
    def test_consume_allows_continue(self):
        b = IterationBudget(max_iterations=5)
        assert b.consume() is True
        assert b.used_iterations == 1

    def test_consume_stops_at_iteration_limit(self):
        b = IterationBudget(max_iterations=2)
        assert b.consume() is True
        assert b.consume() is True
        assert b.consume() is False

    def test_remaining_iterations(self):
        b = IterationBudget(max_iterations=5)
        assert b.remaining_iterations == 5
        b.consume()
        assert b.remaining_iterations == 4

    def test_refund(self):
        b = IterationBudget(max_iterations=3)
        b.consume()
        b.refund()
        assert b.used_iterations == 0

    def test_snapshot(self):
        b = IterationBudget(max_iterations=3)
        b.consume()
        used_i, max_i = b.snapshot()
        assert (used_i, max_i) == (1, 3)

    def test_shared_budget_no_overconsume_under_parallel(self):
        """并行缺口共享同一 IterationBudget：并发扣减不超发（原子性）。"""
        budget = IterationBudget(max_iterations=5, min_continuations=999)
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(lambda i: budget.consume(), range(20)))
        assert outcomes.count(True) == 5  # 恰好消耗满配额
        assert outcomes.count(False) == 15
        assert budget.used_iterations == 5

    def test_diminishing_returns_false(self):
        b = IterationBudget(max_iterations=10, diminishing_threshold=500, min_continuations=3)
        assert b.consume(delta_tokens=100) is True
        assert b.consume(delta_tokens=90) is True
        assert b.consume(delta_tokens=80) is True  # 尚未到 min_continuations
        # 第 4 次起检查递减：最近 [90,80] 都 < 500 且当前 70 < 500
        assert b.consume(delta_tokens=70) is False


class TestBudgetControllerCondition1:
    def test_all_gaps_closed(self):
        ctrl = BudgetController()
        gaps = [_gap(status=GapStatus.CLOSED), _gap(status=GapStatus.CONFIRMED)]
        d = ctrl.should_stop(gaps)
        assert d.should_stop
        assert d.reason == StopReason.ALL_GAPS_CLOSED

    def test_no_gaps(self):
        ctrl = BudgetController()
        d = ctrl.should_stop([])
        assert d.should_stop
        assert d.reason == StopReason.NO_GAPS


class TestBudgetControllerCondition2:
    def test_iteration_budget_exhausted(self):
        ctrl = BudgetController(max_iterations=3)
        ctrl.record_iteration()
        ctrl.record_iteration()
        ctrl.record_iteration()
        d = ctrl.should_stop([_gap(status=GapStatus.OPEN)])
        assert d.should_stop
        assert d.reason == StopReason.ITERATION_BUDGET_EXHAUSTED


class TestBudgetControllerCondition3:
    def test_core_satisfaction_reached(self):
        ctrl = BudgetController(core_priority_threshold=8, core_confidence=0.8)
        gaps = [
            _gap("pricing", priority=9, confidence=0.85),
            _gap("features", priority=5, confidence=0.1),
        ]
        d = ctrl.should_stop(gaps)
        assert d.should_stop
        assert d.reason == StopReason.CORE_SATISFACTION_REACHED

    def test_core_not_satisfied(self):
        ctrl = BudgetController()
        gaps = [_gap("pricing", priority=9, confidence=0.5)]
        d = ctrl.should_stop(gaps)
        assert not d.should_stop

    def test_no_core_gap_does_not_stop(self):
        ctrl = BudgetController()
        gaps = [_gap("sentiment", priority=3, confidence=0.9)]
        d = ctrl.should_stop(gaps)
        assert not d.should_stop


class TestBudgetControllerConcurrency:
    def test_record_iteration_thread_safe(self):
        """并行缺口共享 BudgetController：并发 record_iteration 计数不丢失。"""
        ctrl = BudgetController(max_iterations=100)
        with ThreadPoolExecutor(max_workers=8) as pool:
            pool.map(lambda i: ctrl.record_iteration(), range(20))
        assert ctrl.iteration_count == 20