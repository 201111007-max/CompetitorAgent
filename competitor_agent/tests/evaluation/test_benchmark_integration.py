"""评测基准集成门禁（benchmark_design.md §5 / §8）

- fixture 覆盖类型齐全：normal / boundary / safety（accuracy）+ tool_failure（strategy）
- 用例总数 ≥ 20（设计文档 §5 最小集）
- 核心指标门禁：字段准确率 ≥ 0.90、幻觉率 ≤ 0.05、工具选择准确率 ≥ 0.85
- trace 完整率 = 100%（设计文档 §6）
"""
import pytest

from competitor_agent.evaluation.benchmark import (
    ACCURACY_FIXTURE,
    HARNESS_VERSION,
    STRATEGY_FIXTURE,
    Benchmark,
)

pytestmark = pytest.mark.evaluation


def test_case_set_meets_minimum_20():
    report = Benchmark().run()
    assert report.n_cases >= 20


def test_coverage_reaches_design_targets():
    """10 正常 + 5 边界 + 2 安全（accuracy）；≥3 工具失败（strategy）"""
    acc = Benchmark()._load_accuracy(
        Benchmark()._dir / ACCURACY_FIXTURE
    )
    strat = Benchmark()._load_strategy(
        Benchmark()._dir / STRATEGY_FIXTURE
    )

    tags = [t for c in acc for t in c.tags]
    assert tags.count("normal") >= 10
    assert any("boundary" in t for t in tags)
    assert any(t == "safety" for t in tags)

    strat_tags = [t for c in strat for t in c.tags]
    assert strat_tags.count("tool_failure") >= 3


def test_field_accuracy_gate():
    report = Benchmark().run()
    assert report.accuracy.field_accuracy >= 0.90


def test_hallucination_rate_gate():
    report = Benchmark().run()
    assert report.accuracy.hallucination_rate <= 0.05


def test_tool_selection_gate():
    report = Benchmark().run()
    assert report.strategy.tool_selection_accuracy >= 0.85


def test_trace_completeness_full():
    report = Benchmark().run()
    assert report.trace_completeness == 1.0


def test_report_carries_harness_version():
    report = Benchmark().run()
    assert report.harness_version == HARNESS_VERSION
    assert "harness_version" in report.to_dict()