"""设计文档 55 M1：benchmark ``--gate`` 门禁执法

- evaluate_gates：六项门禁（4 项结果级 + 2 项行为级）逐项判定，阈值来自 GATE_* 常量单一来源；
- main --gate：达标 return 0 / 不达标 return 1 且输出含「指标/阈值/实测」差距；
- 默认不加 --gate 恒 0 回归（既有行为逐位不变）；real 无 Key 仍 return 2 不变。
"""
from __future__ import annotations

import pytest

from competitor_agent.evaluation.accuracy_eval import AccuracyMetrics
from competitor_agent.evaluation.behavior_eval import BehaviorMetrics
from competitor_agent.evaluation.benchmark import (
    GATE_FIELD_ACCURACY_MIN,
    GATE_HALLUCINATION_MAX,
    GATE_RECOVERY_RATE_MIN,
    GATE_TOOL_SELECTION_MIN,
    GATE_TRACE_COMPLETENESS,
    Benchmark,
    BenchmarkReport,
    evaluate_gates,
    main,
)
from competitor_agent.evaluation.strategy_eval import StrategyMetrics

pytestmark = pytest.mark.evaluation


def _passing_report() -> BenchmarkReport:
    return BenchmarkReport(
        accuracy=AccuracyMetrics(field_accuracy=1.0, hallucination_rate=0.0),
        strategy=StrategyMetrics(tool_selection_accuracy=1.0),
        n_cases=20,
        trace_completeness=1.0,
        behavior=BehaviorMetrics(
            react_recovery_rate=1.0,
            recovery_n=2,
            retrieval_hit_hybrid=1.0,
            retrieval_hit_lexical=1.0,
            retrieval_n=2,
        ),
    )


class TestEvaluateGates:
    def test_passing_report_all_green(self):
        checks = evaluate_gates(_passing_report())
        assert len(checks) == 7
        assert all(c.passed for c in checks)
        assert [c.name for c in checks] == [
            "field_accuracy",
            "hallucination_rate",
            "tool_selection_accuracy",
            "trace_completeness",
            "behavior.react_recovery_rate",
            "behavior.retrieval_hit_hybrid",
            "behavior.refetch_after_fold",
        ]

    def test_thresholds_come_from_gate_constants(self):
        checks = {c.name: c for c in evaluate_gates(_passing_report())}
        assert checks["field_accuracy"].threshold == f">= {GATE_FIELD_ACCURACY_MIN:.2f}"
        assert checks["hallucination_rate"].threshold == f"<= {GATE_HALLUCINATION_MAX:.2f}"
        assert checks["tool_selection_accuracy"].threshold == f">= {GATE_TOOL_SELECTION_MIN:.2f}"
        assert checks["trace_completeness"].threshold == f"== {GATE_TRACE_COMPLETENESS:.2f}"
        assert checks["behavior.react_recovery_rate"].threshold == f">= {GATE_RECOVERY_RATE_MIN:.2f}"

    def test_boundary_values_pass(self):
        """贴阈值边界：等于阈值判定为达标（>= / <= / == 语义）。"""
        report = BenchmarkReport(
            accuracy=AccuracyMetrics(
                field_accuracy=GATE_FIELD_ACCURACY_MIN,
                hallucination_rate=GATE_HALLUCINATION_MAX,
            ),
            strategy=StrategyMetrics(tool_selection_accuracy=GATE_TOOL_SELECTION_MIN),
            trace_completeness=GATE_TRACE_COMPLETENESS,
            behavior=BehaviorMetrics(
                react_recovery_rate=GATE_RECOVERY_RATE_MIN,
                retrieval_hit_hybrid=0.5,
                retrieval_hit_lexical=0.5,
            ),
        )
        assert all(c.passed for c in evaluate_gates(report))

    @pytest.mark.parametrize(
        ("field", "value", "failing"),
        [
            ("field_accuracy", 0.0, "field_accuracy"),
            ("hallucination_rate", 1.0, "hallucination_rate"),
        ],
    )
    def test_accuracy_metric_failure_flagged(self, field, value, failing):
        report = _passing_report()
        setattr(report.accuracy, field, value)
        checks = evaluate_gates(report)
        by_name = {c.name: c for c in checks}
        assert not by_name[failing].passed
        assert sum(not c.passed for c in checks) == 1

    def test_tool_selection_failure_flagged(self):
        report = _passing_report()
        report.strategy.tool_selection_accuracy = 0.0
        by_name = {c.name: c for c in evaluate_gates(report)}
        assert not by_name["tool_selection_accuracy"].passed

    def test_trace_incomplete_flagged(self):
        report = _passing_report()
        report.trace_completeness = 0.5
        by_name = {c.name: c for c in evaluate_gates(report)}
        assert not by_name["trace_completeness"].passed

    def test_recovery_rate_failure_flagged(self):
        report = _passing_report()
        report.behavior.react_recovery_rate = 0.0
        by_name = {c.name: c for c in evaluate_gates(report)}
        assert not by_name["behavior.react_recovery_rate"].passed

    def test_hybrid_below_lexical_flagged(self):
        """设计文档 42：hybrid 不得劣于 lexical（向量层退化可感知）。"""
        report = _passing_report()
        report.behavior.retrieval_hit_hybrid = 0.5
        report.behavior.retrieval_hit_lexical = 1.0
        checks = evaluate_gates(report)
        by_name = {c.name: c for c in checks}
        assert not by_name["behavior.retrieval_hit_hybrid"].passed
        assert "lexical(1.0000)" in by_name["behavior.retrieval_hit_hybrid"].threshold


class TestMainGate:
    def test_gate_pass_returns_0(self, tmp_path, capsys):
        """真实 mock 全量跑（与 CI 同口径）：达标 return 0 且打印门禁表。"""
        rc = main([
            "--gate",
            "--out", str(tmp_path / "b.csv"),
            "--report", str(tmp_path / "b.md"),
        ])
        out = capsys.readouterr().out
        assert rc == 0
        assert "门禁判定（--gate）" in out
        assert "门禁全部达标（7/7）" in out
        assert "PASS field_accuracy" in out

    def test_gate_failure_returns_1_with_gap(self, tmp_path, capsys, monkeypatch):
        """不达标 return 1，输出含指标/阈值/实测差距。"""
        failing = _passing_report()
        failing.accuracy.field_accuracy = 0.5
        monkeypatch.setattr(Benchmark, "run", lambda self: failing)
        rc = main([
            "--gate",
            "--out", str(tmp_path / "b.csv"),
            "--report", str(tmp_path / "b.md"),
        ])
        out = capsys.readouterr().out
        assert rc == 1
        assert "FAIL field_accuracy" in out
        assert "实测 0.5000" in out
        assert f">= {GATE_FIELD_ACCURACY_MIN:.2f}" in out
        assert "1/7 项不达标" in out

    def test_no_gate_keeps_return_0_even_when_failing(self, tmp_path, monkeypatch):
        """默认不加 --gate 行为逐位不变：即使门禁不达标也恒 0。"""
        failing = _passing_report()
        failing.accuracy.field_accuracy = 0.0
        failing.trace_completeness = 0.0
        monkeypatch.setattr(Benchmark, "run", lambda self: failing)
        rc = main(["--out", str(tmp_path / "b.csv"), "--report", str(tmp_path / "b.md")])
        assert rc == 0

    def test_real_without_key_still_returns_2(self, capsys):
        """real 无 Key 显式报错 return 2（设计文档 37），--gate 不改变该前置校验。"""
        rc = main(["--llm", "real", "--gate"])
        out = capsys.readouterr().out
        assert rc == 2
        assert "API Key" in out
