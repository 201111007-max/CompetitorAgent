"""evaluation 包：评测体系（M3）"""
from competitor_agent.evaluation.accuracy_eval import AccuracyEvaluator, AccuracyMetrics, EvalCase
from competitor_agent.evaluation.benchmark import Benchmark, BenchmarkReport
from competitor_agent.evaluation.golden import (
    GOLDEN_DIR,
    GoldenAssertion,
    GoldenEvaluator,
    GoldenJudge,
    GoldenResult,
    GoldenTask,
    GoldenVerdict,
    KeywordGoldenJudge,
    LLMGoldenJudge,
    build_golden_judge,
    load_golden_tasks,
)
from competitor_agent.evaluation.history import (
    DEFAULT_HISTORY_PATH,
    append_history,
    git_head,
    load_history,
    snapshot,
)
from competitor_agent.evaluation.history import (
    diff as eval_diff,
)
from competitor_agent.evaluation.strategy_eval import StrategyCase, StrategyEvaluator, StrategyMetrics

__all__ = [
    "DEFAULT_HISTORY_PATH",
    "GOLDEN_DIR",
    "AccuracyEvaluator",
    "AccuracyMetrics",
    "Benchmark",
    "BenchmarkReport",
    "EvalCase",
    "GoldenAssertion",
    "GoldenEvaluator",
    "GoldenJudge",
    "GoldenResult",
    "GoldenTask",
    "GoldenVerdict",
    "KeywordGoldenJudge",
    "LLMGoldenJudge",
    "StrategyCase",
    "StrategyEvaluator",
    "StrategyMetrics",
    "append_history",
    "build_golden_judge",
    "eval_diff",
    "git_head",
    "load_golden_tasks",
    "load_history",
    "snapshot",
]
