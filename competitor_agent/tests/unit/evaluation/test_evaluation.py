"""evaluation/ 评测体系测试（M3 3.3/3.4/3.5）"""
from competitor_agent.evaluation.accuracy_eval import AccuracyEvaluator, EvalCase
from competitor_agent.evaluation.benchmark import ACCURACY_FIXTURE, STRATEGY_FIXTURE, Benchmark
from competitor_agent.evaluation.strategy_eval import StrategyCase, StrategyEvaluator


class TestAccuracyEvaluator:
    def test_exact_match_scores_100(self):
        cases = [
            EvalCase(
                task="x",
                prediction={"pricing_pro": "$20/month"},
                ground_truth={"pricing_pro": "$20/month"},
            )
        ]
        m = AccuracyEvaluator().evaluate(cases)
        assert m.field_accuracy == 1.0
        assert m.hallucination_rate == 0.0
        assert m.f1 == 1.0

    def test_wrong_value_hits_zero_accuracy(self):
        cases = [
            EvalCase(
                task="x",
                prediction={"pricing_pro": "$99"},
                ground_truth={"pricing_pro": "$20"},
            )
        ]
        m = AccuracyEvaluator().evaluate(cases)
        assert m.field_accuracy == 0.0
        assert m.f1 == 0.0

    def test_hallucinated_field_inflates_rate(self):
        cases = [
            EvalCase(
                task="x",
                prediction={"pricing_pro": "$20", "pricing_team": "$9999"},
                ground_truth={"pricing_pro": "$20", "pricing_team": "$40"},
            )
        ]
        m = AccuracyEvaluator().evaluate(cases)
        assert m.field_accuracy == 0.5
        assert m.hallucination_rate > 0.0

    def test_empty_cases_return_zero_metrics(self):
        m = AccuracyEvaluator().evaluate([])
        assert m.field_accuracy == 0.0


class TestStrategyEvaluator:
    def test_first_choice_hit(self):
        cases = [
            StrategyCase(task="x", chosen_sources=["official_pricing"], best_source="official_pricing", total_cost=0.01)
        ]
        m = StrategyEvaluator().evaluate(cases)
        assert m.tool_selection_accuracy == 1.0
        assert m.avg_source_rank == 1.0

    def test_second_choice_hit_rank_two(self):
        cases = [
            StrategyCase(
                task="x",
                chosen_sources=["official_home", "spa_extractor"],
                best_source="spa_extractor",
                total_cost=0.05,
            )
        ]
        m = StrategyEvaluator().evaluate(cases)
        assert m.tool_selection_accuracy == 1.0
        assert m.avg_source_rank == 2.0

    def test_missed_best_source(self):
        cases = [
            StrategyCase(task="x", chosen_sources=["official_home"], best_source="spa_extractor", total_cost=0.02)
        ]
        m = StrategyEvaluator().evaluate(cases)
        assert m.tool_selection_accuracy == 0.0

    def test_cost_efficiency_rewards_cheap_success(self):
        cheap = StrategyCase(task="a", chosen_sources=["official_docs"], best_source="official_docs", total_cost=0.01)
        costly = StrategyCase(task="b", chosen_sources=["official_docs"], best_source="official_docs", total_cost=0.1)
        m = StrategyEvaluator().evaluate([cheap, costly])
        assert m.cost_efficiency > 0


class TestBenchmark:
    def test_runs_against_real_fixtures(self):
        b = Benchmark()
        report = b.run()
        assert report.n_cases == 8  # 4 accuracy + 4 strategy
        assert report.loaded_fixtures == [ACCURACY_FIXTURE, STRATEGY_FIXTURE]
        assert 0.0 < report.accuracy.field_accuracy <= 1.0
        assert 0.0 < report.strategy.tool_selection_accuracy <= 1.0

    def test_missing_fixtures_returns_empty(self, tmp_path):
        b = Benchmark(fixtures_dir=tmp_path)
        report = b.run()
        assert report.n_cases == 0
