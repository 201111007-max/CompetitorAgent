"""Benchmark — 评测基准（3.5）

加载 tests/evaluation/fixtures/ 下的标注用例：
- accuracy_cases.json：字段准确率/幻觉率/F1
- strategy_cases.json：工具选择/成本效率
运行镜像评测并汇总为 BenchmarkReport。

- harness 版本：每个分数必须附带版本号（benchmark + subset + harness），防"上个数字误导"。
- trace：每条 case 可带完整执行轨迹（工具/参数/成本/耗时），用于失败归因与回放。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from competitor_agent.evaluation.accuracy_eval import AccuracyEvaluator, AccuracyMetrics, EvalCase
from competitor_agent.evaluation.strategy_eval import StrategyCase, StrategyEvaluator, StrategyMetrics

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "evaluation" / "fixtures"

ACCURACY_FIXTURE = "accuracy_cases.json"
STRATEGY_FIXTURE = "strategy_cases.json"

# 评测 harness 版本：分数 = benchmark + subset + harness。任何评测输出必须带此版本号。
HARNESS_VERSION = "0.2.0"


@dataclass
class BenchmarkReport:
    accuracy: AccuracyMetrics = field(default_factory=AccuracyMetrics)
    strategy: StrategyMetrics = field(default_factory=StrategyMetrics)
    n_cases: int = 0
    loaded_fixtures: list[str] = field(default_factory=list)
    harness_version: str = HARNESS_VERSION
    trace_completeness: float = 0.0  # 有完整 trace 的 case / 总 case
    confusion_matrix: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "harness_version": self.harness_version,
            "n_cases": self.n_cases,
            "trace_completeness": self.trace_completeness,
            "fixtures": self.loaded_fixtures,
            "accuracy": {
                "field_accuracy": self.accuracy.field_accuracy,
                "hallucination_rate": self.accuracy.hallucination_rate,
                "f1": self.accuracy.f1,
                "hallucination_instances": self.accuracy.hallucination_instances,
            },
            "strategy": {
                "tool_selection_accuracy": self.strategy.tool_selection_accuracy,
                "cost_efficiency": self.strategy.cost_efficiency,
                "avg_source_rank": self.strategy.avg_source_rank,
            },
            "confusion_matrix": self.confusion_matrix,
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
            trace_completeness=self._trace_completeness(acc_cases, strat_cases),
            confusion_matrix=self._confusion_matrix(strat_cases),
        )

    def _load_accuracy(self, path: Path) -> list[EvalCase]:
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [
            EvalCase(
                task=c["task"],
                prediction=c["prediction"],
                ground_truth=c["ground_truth"],
                case_id=c.get("case_id", ""),
                competitor=c.get("competitor", ""),
                dimension=c.get("dimension", ""),
                tags=c.get("tags", []),
                sources=c.get("sources", []),
                trace=c.get("trace", []),
            )
            for c in data
        ]

    def _load_strategy(self, path: Path) -> list[StrategyCase]:
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
                case_id=c.get("case_id", ""),
                tags=c.get("tags", []),
                trace=c.get("trace", []),
            )
            for c in data
        ]

    @staticmethod
    def _trace_completeness(acc_cases: list[EvalCase], strat_cases: list[StrategyCase]) -> float:
        """trace 完整率 = 有非空 trace 的 case / 总 case（设计文档 §6 目标 100%）"""
        all_cases = acc_cases + strat_cases
        if not all_cases:
            return 0.0
        with_trace = sum(1 for c in all_cases if c.trace)
        return round(with_trace / len(all_cases), 4)

    @staticmethod
    def _confusion_matrix(strat_cases: list[StrategyCase]) -> dict[str, dict[str, int]]:
        """工具选择混淆矩阵：rows = 标注最优源，cols = Agent 首选源"""
        matrix: dict[str, dict[str, int]] = {}
        for case in strat_cases:
            chosen_first = case.chosen_sources[0] if case.chosen_sources else "(none)"
            row = matrix.setdefault(case.best_source, {})
            row[chosen_first] = row.get(chosen_first, 0) + 1
        return matrix


def _write_csv(report: BenchmarkReport, out: Path) -> None:
    rows = [["harness_version", "metric", "value"]]
    acc = report.to_dict()["accuracy"]
    strat = report.to_dict()["strategy"]
    for k, v in acc.items():
        if k != "hallucination_instances":
            rows.append([report.harness_version, f"accuracy.{k}", str(v)])
    for k, v in strat.items():
        rows.append([report.harness_version, f"strategy.{k}", str(v)])
    rows.append([report.harness_version, "trace_completeness", str(report.trace_completeness)])
    out.write_text("\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8")


def _write_markdown(report: BenchmarkReport, out: Path) -> None:
    """评测报告：均值/方差 + 逐 case 明细 + 幻觉实例清单 + 混淆矩阵 + harness 版本号"""
    lines: list[str] = []
    lines.append(f"# Benchmark Report — harness v{report.harness_version}")
    lines.append(f"\n> generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append(f"> fixtures: {', '.join(report.loaded_fixtures)} | cases: {report.n_cases} | trace completeness: {report.trace_completeness:.0%}")
    lines.append("\n## 指标汇总")
    lines.append("\n| 指标 | 值 |")
    lines.append("|------|----|")
    lines.append(f"| 字段准确率 | {report.accuracy.field_accuracy:.4f} |")
    lines.append(f"| 幻觉率 | {report.accuracy.hallucination_rate:.4f} |")
    lines.append(f"| F1 | {report.accuracy.f1:.4f} |")
    lines.append(f"| 工具选择准确率 | {report.strategy.tool_selection_accuracy:.4f} |")
    lines.append(f"| 成本效率 | {report.strategy.cost_efficiency:.4f} |")
    lines.append(f"| 平均命中排名 | {report.strategy.avg_source_rank:.2f} |")

    lines.append("\n## 逐 case 明细（strategy）")
    lines.append("\n| task | hit | rank | cost | efficiency |")
    lines.append("|------|-----|------|------|------------|")
    for pc in report.strategy.per_case:
        lines.append(
            f"| {pc['task']} | {pc['hit']} | {pc['rank']} | {pc['cost']} | {pc['efficiency']:.4f} |"
        )

    lines.append("\n## 幻觉实例清单")
    if report.accuracy.hallucination_instances:
        lines.append("\n| case | field | prediction | ground_truth |")
        lines.append("|------|-------|------------|--------------|")
        for inst in report.accuracy.hallucination_instances:
            lines.append(
                f"| {inst['case_id'] or inst['task']} | {inst['field']} | {inst['prediction']} | {inst['ground_truth']} |"
            )
    else:
        lines.append("\n- 无（审计通过）")

    lines.append("\n## 工具选择混淆矩阵（rows=最优源, cols=首选源）")
    lines.append("\n| 最优源 \\ 首选 | 命中数 |")
    lines.append("|---------------|--------|")
    for best, row in report.confusion_matrix.items():
        total = sum(row.values())
        lines.append(f"| {best} | {total} |")
        for chosen, count in row.items():
            lines.append(f"  - {chosen}: {count}")

    lines.append("\n> 分数有效范围：harness v" + report.harness_version + "，改 fixture/依赖/harness 需更新版本号。")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="benchmark", description="competitor_agent 评测基准")
    parser.add_argument("--out", type=Path, default=Path("reports/benchmark.csv"), help="CSV 输出路径")
    parser.add_argument("--report", type=Path, default=Path("reports/benchmark.md"), help="Markdown 报告路径")
    args = parser.parse_args(argv)

    report = Benchmark().run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(report, args.out)
    _write_markdown(report, args.report)
    print(f"n_cases={report.n_cases} trace={report.trace_completeness:.0%} field_acc={report.accuracy.field_accuracy:.4f} "
          f"halluc={report.accuracy.hallucination_rate:.4f} tool_sel={report.strategy.tool_selection_accuracy:.4f} "
          f"cost_eff={report.strategy.cost_efficiency:.4f} harness_v{report.harness_version}")
    print(f"csv: {args.out}")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["HARNESS_VERSION", "Benchmark", "BenchmarkReport"]
