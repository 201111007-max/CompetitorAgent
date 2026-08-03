"""Benchmark — 评测基准（3.5）

加载 tests/evaluation/fixtures/ 下的标注用例：
- accuracy_cases.json：字段准确率/幻觉率/F1
- strategy_cases.json：工具选择/成本效率
运行镜像评测并汇总为 BenchmarkReport。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from competitor_agent.evaluation.accuracy_eval import AccuracyEvaluator, AccuracyMetrics, EvalCase
from competitor_agent.evaluation.strategy_eval import StrategyCase, StrategyEvaluator, StrategyMetrics

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "evaluation" / "fixtures"

ACCURACY_FIXTURE = "accuracy_cases.json"
STRATEGY_FIXTURE = "strategy_cases.json"


@dataclass
class BenchmarkReport:
    accuracy: AccuracyMetrics = field(default_factory=AccuracyMetrics)
    strategy: StrategyMetrics = field(default_factory=StrategyMetrics)
    n_cases: int = 0
    loaded_fixtures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_cases": self.n_cases,
            "fixtures": self.loaded_fixtures,
            "accuracy": {
                "field_accuracy": self.accuracy.field_accuracy,
                "hallucination_rate": self.accuracy.hallucination_rate,
                "f1": self.accuracy.f1,
            },
            "strategy": {
                "tool_selection_accuracy": self.strategy.tool_selection_accuracy,
                "cost_efficiency": self.strategy.cost_efficiency,
                "avg_source_rank": self.strategy.avg_source_rank,
            },
        }


class Benchmark:
    """运行完整 benchmark 评测"""

    def __init__(
        self,
        fixtures_dir: Path | None = None,
        accuracy_eval: AccuracyEvaluator | None = None,
        strategy_eval: StrategyEvaluator | None = None,
    ) -> None:
        self._dir = fixtures_dir or FIXTURES_DIR
        self._accuracy = accuracy_eval or AccuracyEvaluator()
        self._strat = strategy_eval or StrategyEvaluator()

    def run(self) -> BenchmarkReport:
        acc_cases = self._load_accuracy(self._dir / ACCURACY_FIXTURE)
        strat_cases = self._load_strategy(self._dir / STRATEGY_FIXTURE)

        acc_metrics = self._accuracy.evaluate(acc_cases)
        strat_metrics = self._strat.evaluate(strat_cases)
        return BenchmarkReport(
            accuracy=acc_metrics,
            strategy=strat_metrics,
            n_cases=len(acc_cases) + len(strat_cases),
            loaded_fixtures=[ACCURACY_FIXTURE, STRATEGY_FIXTURE],
        )

    def _load_accuracy(self, path: Path) -> list[EvalCase]:  # pragma: no cover - 依赖真实 fixture 文件
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [EvalCase(task=c["task"], prediction=c["prediction"], ground_truth=c["ground_truth"]) for c in data]

    def _load_strategy(self, path: Path) -> list[StrategyCase]:  # pragma: no cover - 依赖真实 fixture 文件
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [
            StrategyCase(
                task=c["task"],
                chosen_sources=c["chosen_sources"],
                best_source=c["best_source"],
                total_cost=c.get("total_cost", 0.0),
                outcome_complete=c.get("outcome_complete", True),
                depth=c.get("depth", len(c["chosen_sources"])),
            )
            for c in data
        ]


__all__ = ["Benchmark", "BenchmarkReport"]