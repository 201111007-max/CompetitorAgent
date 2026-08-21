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
    GATE_FIELD_ACCURACY_MIN,
    GATE_HALLUCINATION_MAX,
    GATE_TOOL_SELECTION_MIN,
    GATE_TRACE_COMPLETENESS,
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
        assert report.accuracy.field_accuracy >= GATE_FIELD_ACCURACY_MIN

    def test_hallucination_rate_gate(self):
        report = Benchmark().run()
        assert report.accuracy.hallucination_rate <= GATE_HALLUCINATION_MAX

    def test_tool_selection_gate(self):
        report = Benchmark().run()
        assert report.strategy.tool_selection_accuracy >= GATE_TOOL_SELECTION_MIN

    def test_trace_completeness_full(self):
        report = Benchmark().run()
        assert report.trace_completeness == GATE_TRACE_COMPLETENESS


class TestDesign29NewDimensionGates:
    """设计文档 29：生态/口碑/时间线覆盖盲区门禁"""

    def test_new_dimension_coverage(self):
        """新维度 fixture 被发现：生态 ≥3 / 口碑 ≥4 / 时间线 ≥1 / 空数据 ≥2"""
        b = Benchmark()
        acc = b._load_accuracy(b._dir / ACCURACY_FIXTURE)
        tags = [t for c in acc for t in c.tags]
        assert tags.count("ecosystem") >= 3
        assert tags.count("sentiment") >= 4
        assert tags.count("roadmap") >= 1
        assert tags.count("empty_signal") >= 2

    def test_new_dimension_accuracy_gate(self):
        """新维度字段准确率 ≥ 0.80（设计文档 29 §4）"""
        report = Benchmark().run()
        for dim in ("ecosystem", "sentiment", "roadmap"):
            if dim in report.accuracy_by_dimension:
                assert report.accuracy_by_dimension[dim] >= 0.80

    def test_empty_signal_no_fabrication(self):
        """生态/口碑空数据不得编造：empty_signal 用例字段准确率 100%、幻觉率 0"""
        report = Benchmark().run()
        b = Benchmark()
        empty_ids = {
            c.case_id
            for c in b._load_accuracy(b._dir / ACCURACY_FIXTURE)
            if "empty_signal" in c.tags
        }
        assert empty_ids, "缺少空数据护栏用例"
        empty_cases = [pc for pc in report.accuracy.per_case if pc["case_id"] in empty_ids]
        assert len(empty_cases) == len(empty_ids)
        for pc in empty_cases:
            assert pc["field_accuracy"] == 1.0, f"{pc['case_id']} 空数据产生了具体结论（编造）"
            assert pc["hallucination_rate"] == 0.0, f"{pc['case_id']} 空数据存在幻觉"


def test_report_carries_harness_version():
    report = Benchmark().run()
    assert report.harness_version == HARNESS_VERSION
    assert "harness_version" in report.to_dict()