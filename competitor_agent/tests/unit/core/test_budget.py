"""core/budget.py + budget_controller.py 单测：四条件终止分支"""
from competitor_agent.core.budget import IterationBudget
from competitor_agent.core.budget_controller import BudgetController, StopReason
from competitor_agent.domain_types import GapStatus, InfoGap


def _gap(field="pricing", priority=5, confidence=0.0, status=GapStatus.OPEN):
    return InfoGap(field=field, priority=priority, confidence=confidence, status=status)


class TestIterationBudget:
    def test_consume_allows_continue(self):
        b = IterationBudget(max_iterations=5, cost_limit=1.0)
        assert b.consume(delta_cost=0.1) is True
        assert b.used_iterations == 1
        assert b.used_cost == 0.1

    def test_consume_stops_at_iteration_limit(self):
        b = IterationBudget(max_iterations=2, cost_limit=1.0)
        assert b.consume() is True
        assert b.consume() is True
        assert b.consume() is False

    def test_consume_stops_at_cost_limit(self):
        b = IterationBudget(max_iterations=10, cost_limit=0.5)
        assert b.consume(delta_cost=0.4) is True
        assert b.consume(delta_cost=0.4) is True  # 0.8 >= 0.5，仍在预算内
        assert b.consume(delta_cost=0.4) is False  # 下次检查已超限

    def test_remaining_iterations(self):
        b = IterationBudget(max_iterations=5, cost_limit=1.0)
        assert b.remaining_iterations == 5
        b.consume()
        assert b.remaining_iterations == 4

    def test_refund(self):
        b = IterationBudget(max_iterations=3, cost_limit=1.0)
        b.consume()
        b.refund()
        assert b.used_iterations == 0

    def test_snapshot(self):
        b = IterationBudget(max_iterations=3, cost_limit=0.5)
        b.consume(delta_cost=0.2)
        used_i, max_i, used_c, max_c = b.snapshot()
        assert (used_i, max_i, used_c, max_c) == (1, 3, 0.2, 0.5)

    def test_diminishing_returns_false(self):
        b = IterationBudget(max_iterations=10, cost_limit=1.0, diminishing_threshold=500, min_continuations=3)
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
    def test_cost_limit_reached(self):
        ctrl = BudgetController(cost_limit=1.0)
        ctrl.record_iteration(cost=0.6)
        ctrl.record_iteration(cost=0.6)
        d = ctrl.should_stop([_gap(status=GapStatus.OPEN)])
        assert d.should_stop
        assert d.reason == StopReason.COST_LIMIT_REACHED


class TestBudgetControllerCondition4:
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


class TestBudgetControllerVerifierHook:
    def test_verifier_can_force_stop(self):
        class ForceStopVerifier:
            def verify(self, gaps, budget_state):
                from competitor_agent.interfaces.context import StopDecision

                return StopDecision(should_stop=True, reason="hook")

        ctrl = BudgetController(verifier=ForceStopVerifier())
        d = ctrl.should_stop([_gap(status=GapStatus.OPEN)])
        assert d.should_stop
        assert d.reason == "hook"

    def test_verifier_can_force_continue(self):
        class BlockStopVerifier:
            def verify(self, gaps, budget_state):
                from competitor_agent.interfaces.context import StopDecision

                return StopDecision(should_stop=False)

        ctrl = BudgetController(verifier=BlockStopVerifier())
        gaps = [_gap(status=GapStatus.CONFIRMED)]
        d = ctrl.should_stop(gaps)
        assert not d.should_stop

    def test_budget_state_passed_to_verifier(self):
        captured = {}

        class CaptureVerifier:
            def verify(self, gaps, budget_state):
                captured["state"] = budget_state
                from competitor_agent.interfaces.context import StopDecision

                return StopDecision(should_stop=False)

        ctrl = BudgetController(verifier=CaptureVerifier())
        ctrl.record_iteration(cost=0.3)
        ctrl.should_stop([_gap(status=GapStatus.OPEN)])
        assert captured["state"].iterations_used == 1
        assert captured["state"].total_cost == 0.3
        assert captured["state"].max_iterations == 10