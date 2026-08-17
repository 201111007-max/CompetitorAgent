"""真实 LLM 评测报告（设计文档 37）— 报告字段 / 成本核算 / tag 过滤 / 成本护栏 / mock vs real

- 报告字段：BenchmarkReport 含 llm_mode / cost_usd / per_case_cost / cost_limit_usd / budget_aborted，
  to_dict / CSV / Markdown 渲染分支正确（mock 与 real）。
- 成本核算：共享 LLM 实例（注入 mock call_func）跨 case 累计 cost_usd（复用 llm._log_call）。
- tag 过滤：--tag normal 只跑 normal 子集（控制成本），缺省全量。
- 成本护栏：cost_limit_usd 超限中止并标注 budget_exhausted 失败（复用设计文档 31 分类）。
- mock vs real 对比：real 报告内嵌 mock 基线「mock vs real」段，直答"评测是不是自证"。
- real 冒烟（skipif 无 Key）：有 Key 时 --llm real 跑 normal 子集产真实质量报告。
"""
import json

import pytest

from competitor_agent.evaluation.benchmark import (
    ACCURACY_FIXTURE,
    Benchmark,
    BenchmarkMockLLM,
    BenchmarkReport,
    STRATEGY_FIXTURE,
    _write_csv,
    _write_markdown,
    build_benchmark_api,
    build_real_llm,
)
from competitor_agent.llm.client import LLMClient


def _shared_mock_llm() -> LLMClient:
    """共享 mock LLM：走真实 LLMClient 成本核算路径，但不联网、无 Key。"""
    return LLMClient(call_func=BenchmarkMockLLM().complete)


class TestReportFields:
    """设计文档 37 §5：BenchmarkReport 字段 + to_dict"""

    def test_default_mock_has_llm_mode(self):
        report = Benchmark(llm_mode="mock").run()
        assert report.llm_mode == "mock"
        assert report.cost_usd == 0.0
        assert report.cost_limit_usd is None
        assert report.budget_aborted is False

    def test_to_dict_carries_real_fields(self):
        report = Benchmark(llm_mode="mock").run()
        d = report.to_dict()
        assert d["llm_mode"] == "mock"
        assert "cost_usd" in d
        assert "per_case_cost" in d
        assert "cost_limit_usd" in d
        assert "budget_aborted" in d

    def test_report_instantiates_with_real_mode(self):
        report = BenchmarkReport(llm_mode="real", cost_usd=0.5, per_case_cost={"c1": 0.5})
        assert report.llm_mode == "real"
        assert report.to_dict()["cost_usd"] == 0.5


class TestCostAccounting:
    """设计文档 37 §2.3/§3.1：共享实例跨 case 累计成本"""

    def test_shared_llm_accumulates_cost(self):
        report = Benchmark(llm_mode="real", llm=_shared_mock_llm()).run()
        assert report.llm_mode == "real"
        assert report.cost_usd > 0.0
        assert len(report.per_case_cost) == report.n_cases
        assert all(v >= 0.0 for v in report.per_case_cost.values())

    def test_mock_no_shared_llm_cost_zero(self):
        report = Benchmark(llm_mode="mock").run()
        assert report.cost_usd == 0.0
        assert report.per_case_cost and all(v == 0.0 for v in report.per_case_cost.values())


class TestTagFilter:
    """设计文档 37 §3.1：--tag 子集过滤（先跑 normal 控制成本）"""

    def test_tag_normal_reduces_cases(self):
        b = Benchmark()
        full = Benchmark().run()
        normal = Benchmark(tag="normal").run()
        assert normal.n_cases < full.n_cases
        assert normal.n_cases >= 2

    def test_tag_matches_fixture_tags(self):
        b = Benchmark()
        acc = b._load_accuracy(b._dir / ACCURACY_FIXTURE)
        strat = b._load_strategy(b._dir / STRATEGY_FIXTURE)
        expected = sum(1 for c in acc if "normal" in c.tags) + sum(1 for c in strat if "normal" in c.tags)
        assert Benchmark(tag="normal").run().n_cases == expected


class TestCostGuardrail:
    """设计文档 37 §3.3：成本护栏中止 → budget_exhausted（复用设计文档 31 分类）"""

    def test_budget_limit_zero_aborts(self):
        report = Benchmark(llm_mode="real", llm=_shared_mock_llm(), cost_limit_usd=0.0).run()
        assert report.budget_aborted is True
        assert report.cost_limit_usd == 0.0
        assert report.failure_stats.get("budget_exhausted", 0) >= 1

    def test_no_limit_not_aborted(self):
        report = Benchmark(llm_mode="real", llm=_shared_mock_llm()).run()
        assert report.budget_aborted is False

    def test_reasonable_limit_completes(self):
        report = Benchmark(llm_mode="real", llm=_shared_mock_llm(), cost_limit_usd=1.0).run()
        assert report.budget_aborted is False
        assert report.cost_usd < 1.0


class TestRenderBranches:
    """设计文档 37 §5：mock / real 渲染分支 + mock vs real 对比段"""

    def test_markdown_includes_mode_and_cost(self, tmp_path):
        report = Benchmark(llm_mode="real", llm=_shared_mock_llm()).run()
        out = tmp_path / "benchmark_real.md"
        _write_markdown(report, out)
        text = out.read_text(encoding="utf-8")
        assert "llm_mode: real" in text
        assert "累计成本" in text
        assert "| LLM 模式 | real |" in text
        assert "cost_usd" in text

    def test_markdown_mock_vs_real_section(self, tmp_path):
        mock_report = Benchmark(llm_mode="mock").run()
        real_report = Benchmark(llm_mode="real", llm=_shared_mock_llm()).run()
        out = tmp_path / "benchmark_real.md"
        _write_markdown(real_report, out, mock_report=mock_report)
        text = out.read_text(encoding="utf-8")
        assert "## mock vs real 对比" in text
        assert "mock" in text and "real" in text

    def test_markdown_mock_no_comparison(self, tmp_path):
        report = Benchmark(llm_mode="mock").run()
        out = tmp_path / "benchmark.md"
        _write_markdown(report, out)
        text = out.read_text(encoding="utf-8")
        assert "## mock vs real 对比" not in text
        assert "| LLM 模式 | mock |" in text

    def test_csv_includes_mode_cost_and_vs(self, tmp_path):
        mock_report = Benchmark(llm_mode="mock").run()
        real_report = Benchmark(llm_mode="real", llm=_shared_mock_llm()).run()
        out = tmp_path / "benchmark_real.csv"
        _write_csv(real_report, out, mock_report=mock_report)
        text = out.read_text(encoding="utf-8")
        assert "llm_mode" in text and "real" in text
        assert "cost_usd" in text
        assert "vs.mock.accuracy.field_accuracy" in text
        assert "cost.case." in text


class TestRealSmoke:
    """设计文档 37 §5 集成：有 Key 时 --llm real 跑 normal 子集产真实质量报告；无 Key skipif"""

    def test_real_mode_builds_llm_from_config(self):
        # 无 Key 也能构造（真正调用时才抛错）；不联网不阻塞 CI
        llm = build_real_llm()
        assert isinstance(llm, LLMClient)

    @pytest.mark.skipif(not LLMClient.has_api_key(), reason="无 API Key（OPENAI/DEEPSEEK/LLM_API_KEY），跳过真实 LLM 评测")
    def test_real_smoke_normal_subset(self, tmp_path):
        """有 Key 时真实调用：2-3 条 normal 用例 → 报告含真实质量指标与成本"""
        if not LLMClient.has_api_key():
            pytest.skip("运行期无 LLM API Key（隔离环境已清除），跳过真实 LLM 评测")
        report = Benchmark(llm_mode="real", llm=build_real_llm(), tag="normal", cost_limit_usd=0.5).run()
        assert report.llm_mode == "real"
        assert report.n_cases >= 2
        assert report.cost_usd >= 0.0
        assert report.accuracy.field_accuracy >= 0.0
        assert report.budget_aborted is False
        out = tmp_path / "real.csv"
        _write_csv(report, out, mock_report=Benchmark(llm_mode="mock", tag="normal").run())
        assert "vs.mock." in out.read_text(encoding="utf-8")

    def test_build_benchmark_api_reuses_shared_llm(self):
        shared = _shared_mock_llm()
        api = build_benchmark_api(object(), llm_mode="real", llm=shared)
        assert api is not None
        assert api._llm is shared


def test_mock_regression_unchanged():
    """回归：--llm mock 输出与既有断言兼容（字段准确率/幻觉率/工具选择/trace）"""
    report = Benchmark(llm_mode="mock").run()
    assert report.accuracy.field_accuracy == 1.0
    assert report.accuracy.hallucination_rate == 0.0
    assert report.strategy.tool_selection_accuracy >= 0.85
    assert report.trace_completeness == 1.0
