"""评测基准集成门禁（benchmark_design.md §5 / §8）— 真实执行

- Benchmark.run() 对每个 case 真实调用 CompetitorAnalysisAPI.analyze()
  （mock LLM + 固定网页内容，无网络、无 Key，CI 可复现）。
- coverage：normal ≥10 / boundary ≥5 / safety ≥2（accuracy）+ tool_failure ≥3（strategy）
- 门禁阈值反映真实输出：字段准确率 ≥0.90、幻觉率 ≤0.05、工具选择准确率 ≥0.85、
  trace（真实证据）完整率 = 100%。
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
    b = Benchmark()
    acc = b._load_accuracy(b._dir / ACCURACY_FIXTURE)
    strat = b._load_strategy(b._dir / STRATEGY_FIXTURE)

    tags = [t for c in acc for t in c.tags]
    assert tags.count("normal") >= 10
    assert tags.count("boundary") >= 5
    assert tags.count("safety") >= 2

    strat_tags = [t for c in strat for t in c.tags]
    assert strat_tags.count("tool_failure") >= 3


class TestRealExecutionGates:
    """门禁基于真实系统输出（mock LLM + 确定性采集），非 fixture 自证。"""

    def test_field_accuracy_gate(self):
        report = Benchmark().run()
        assert report.accuracy.field_accuracy >= 0.90

    def test_hallucination_rate_gate(self):
        report = Benchmark().run()
        assert report.accuracy.hallucination_rate <= 0.05

    def test_tool_selection_gate(self):
        report = Benchmark().run()
        assert report.strategy.tool_selection_accuracy >= 0.85

    def test_trace_completeness_full(self):
        report = Benchmark().run()
        assert report.trace_completeness == 1.0


def test_report_carries_harness_version():
    report = Benchmark().run()
    assert report.harness_version == HARNESS_VERSION
    assert "harness_version" in report.to_dict()