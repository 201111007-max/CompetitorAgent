"""失败类型统计（设计文档 31）— 五类分类 + 聚合 + 分布报告

- classify_case：5 类场景（源 404 / 幻觉 / 页面无价 / 抽取值错 / 预算触停）+ 全命中返回空 + 优先级；
- _classify_failures：混合构造 case 的计数 / 占比 / 逐条样本 / 去重；
- 集成：自定义 fixtures（真实执行链路，mock LLM + 固定页面）→ failure_stats 符合预期；
  默认 fixtures → 报告含「失败类型分布」表、CSV 含 failure 行、to_dict 携带新字段。
"""
import json

from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.observation import SourceEvidence
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult
from competitor_agent.evaluation.accuracy_eval import EvalCase
from competitor_agent.evaluation.benchmark import (
    _classify_failures,
    _write_csv,
    _write_markdown,
    Benchmark,
)
from competitor_agent.evaluation.failure import FailureRecord, FailureType, classify_case
from competitor_agent.evaluation.strategy_eval import StrategyCase


def _case(case_id: str = "c1", prediction: dict | None = None, ground_truth: dict | None = None) -> EvalCase:
    return EvalCase(
        task=f"task-{case_id}",
        prediction=prediction or {},
        ground_truth=ground_truth or {},
        case_id=case_id,
        dimension="pricing",
    )


def _report(urls: list[str] | None = None) -> CompetitorReport:
    result = DimensionResult(
        dimension="pricing",
        summary="s",
        details={},
        confidence=0.8,
        evidence=[
            SourceEvidence(source_name="web_extractor", url=u)
            for u in (urls or [])
        ],
    )
    return CompetitorReport(competitor=Competitor(name="cursor"), dimension_results=[result])


class TestClassifyCase:
    """设计文档 31 §5：5 类失败场景各归入正确 FailureType"""

    def test_all_matched_returns_empty(self):
        pred = {"pro": "$20/month"}
        gt = {"pro": "$20/month"}
        assert classify_case(_case(prediction=pred, ground_truth=gt), pred, gt) == []

    def test_source_unavailable(self):
        pred = {"pro": ""}
        gt = {"pro": "$20/month"}
        recs = classify_case(_case(prediction=pred, ground_truth=gt), pred, gt, status_hints={"source_unavailable": True})
        assert len(recs) == 1
        assert recs[0].failure_type == FailureType.SOURCE_UNAVAILABLE

    def test_blocked_hint_same_as_source_unavailable(self):
        pred = {"pro": ""}
        gt = {"pro": "$20/month"}
        recs = classify_case(_case(prediction=pred, ground_truth=gt), pred, gt, status_hints={"blocked": True})
        assert recs[0].failure_type == FailureType.SOURCE_UNAVAILABLE

    def test_hallucination(self):
        """预测字段无真值支持（无共享 token）→ HALLUCINATION"""
        pred = {"pro": "$20/month"}
        gt = {"pro": "free tier"}
        recs = classify_case(_case(prediction=pred, ground_truth=gt), pred, gt)
        assert recs[0].failure_type == FailureType.HALLUCINATION

    def test_no_data(self):
        """源有响应但页面无目标信息 → 预测全空 → NO_DATA"""
        pred = {"pro": ""}
        gt = {"pro": "$20/month"}
        recs = classify_case(_case(prediction=pred, ground_truth=gt), pred, gt)
        assert recs[0].failure_type == FailureType.NO_DATA

    def test_parse_failure(self):
        """部分命中：结构对上、值不对（非幻觉，team 缺失）→ PARSE_FAILURE"""
        pred = {"pro": "$20/month", "team": ""}
        gt = {"pro": "$20/month", "team": "$40/month"}
        recs = classify_case(_case(prediction=pred, ground_truth=gt), pred, gt)
        assert recs[0].failure_type == FailureType.PARSE_FAILURE

    def test_budget_exhausted(self):
        pred = {"pro": ""}
        gt = {"pro": "$20/month"}
        recs = classify_case(_case(prediction=pred, ground_truth=gt), pred, gt, status_hints={"budget_exhausted": True})
        assert recs[0].failure_type == FailureType.BUDGET_EXHAUSTED

    def test_hallucination_takes_precedence_over_budget(self):
        pred = {"pro": "$20/month"}
        gt = {"pro": "free tier"}
        recs = classify_case(_case(prediction=pred, ground_truth=gt), pred, gt, status_hints={"budget_exhausted": True})
        assert recs[0].failure_type == FailureType.HALLUCINATION

    def test_evidence_urls_collected_from_report(self):
        pred = {"pro": ""}
        gt = {"pro": "$20/month"}
        recs = classify_case(_case(prediction=pred, ground_truth=gt), pred, gt, _report(["https://a.com", "https://b.com"]))
        assert recs[0].evidence_urls == ["https://a.com", "https://b.com"]

    def test_record_to_dict(self):
        rec = FailureRecord("c1", "pricing", FailureType.NO_DATA, "detail", ["https://a.com"])
        d = rec.to_dict()
        assert d["case_id"] == "c1"
        assert d["failure_type"] == "no_data"
        assert d["evidence_urls"] == ["https://a.com"]


class TestClassifyFailures:
    """设计文档 31 §5：混合 case 的聚合计数 / 逐条样本 / 去重"""

    def _acc(self, case_id: str, pred: dict, gt: dict) -> EvalCase:
        return _case(case_id=case_id, prediction=pred, ground_truth=gt)

    def test_aggregates_counts_and_records(self):
        acc = [
            self._acc("ok", {"pro": "$20/month"}, {"pro": "$20/month"}),   # 全命中，不失败
            self._acc("halluc", {"pro": "$20/month"}, {"pro": "free tier"}),  # HALLUCINATION
            self._acc("nodata", {"pro": ""}, {"pro": "$20/month"}),          # NO_DATA
        ]
        strat = [
            StrategyCase(task="s1", chosen_sources=["https://x.com"], best_source="https://nope.com", case_id="s1"),
        ]
        stats, records = _classify_failures(acc, strat, {})
        assert stats == {"hallucination": 1, "no_data": 1, "parse_failure": 1}
        assert len(records) == 3

    def test_strategy_empty_sources_is_source_unavailable(self):
        strat = [StrategyCase(task="s2", chosen_sources=[], best_source="https://x.com", case_id="s2")]
        stats, records = _classify_failures([], strat, {})
        assert stats == {"source_unavailable": 1}
        assert records[0]["failure_type"] == "source_unavailable"
        assert records[0]["case_id"] == "s2"

    def test_dedup_same_case_type(self):
        dup = self._acc("dup", {"pro": "$20/month"}, {"pro": "free tier"})
        stats, records = _classify_failures([dup, dup], [], {})
        assert stats == {"hallucination": 1}
        assert len(records) == 1

    def test_no_failures_empty_stats(self):
        acc = [self._acc("ok", {"pro": "$20/month"}, {"pro": "$20/month"})]
        strat = [StrategyCase(task="s3", chosen_sources=["https://x.com"], best_source="https://x.com", case_id="s3")]
        stats, records = _classify_failures(acc, strat, {})
        assert stats == {}
        assert records == []


# 自定义集成 fixtures：真实执行链路（mock LLM + 固定页面），含各失败类型与通过用例
ACC_FIXTURES = [
    {"case_id": "pass_ok", "competitor": "cursor", "dimension": "pricing", "task": "只分析 cursor 的定价",
     "tags": ["normal"], "mode": "single", "page": "Pro $20/month", "ground_truth": {"pro": "$20/month"}},
    {"case_id": "fail_parse", "competitor": "cursor", "dimension": "pricing", "task": "只分析 cursor 的定价",
     "tags": ["normal"], "mode": "single", "page": "Pro $20/month",
     "ground_truth": {"pro": "$20/month", "team": "$40/month"}},
    {"case_id": "fail_nodata", "competitor": "cursor", "dimension": "pricing", "task": "只分析 cursor 的定价",
     "tags": ["normal"], "mode": "single", "page": "Cursor is a fast code editor.", "ground_truth": {"pro": "$20/month"}},
    {"case_id": "fail_halluc", "competitor": "cursor", "dimension": "pricing", "task": "只分析 cursor 的定价",
     "tags": ["normal"], "mode": "single", "page": "Pro $20/month", "ground_truth": {"pro": "free tier"}},
]

STRAT_FIXTURES = [
    {"case_id": "strat_hit", "competitor": "cursor", "dimension": "pricing", "task": "只分析 cursor 的定价",
     "tags": ["normal"], "mode": "single", "page": "Pro $20/month", "fail_urls": [],
     "best_url": "https://www.cursor.com/pricing"},
    {"case_id": "strat_rumor_miss", "competitor": "cursor", "dimension": "pricing", "task": "只分析 cursor 的定价",
     "tags": ["normal"], "mode": "single", "page": "Pro $20/month", "fail_urls": [],
     "best_url": "https://example.com/rumor"},
]


def _write_fixtures(tmp_path) -> None:
    (tmp_path / "accuracy_cases.json").write_text(json.dumps(ACC_FIXTURES, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "strategy_cases.json").write_text(json.dumps(STRAT_FIXTURES, ensure_ascii=False), encoding="utf-8")


class TestFailureIntegration:
    """设计文档 31 §5 集成：mock LLM + 固定页面真实执行 → failure_stats 符合预期"""

    def test_custom_fixtures_failure_stats(self, tmp_path):
        _write_fixtures(tmp_path)
        report = Benchmark(fixtures_dir=tmp_path).run()
        assert report.failure_stats == {
            "hallucination": 1,
            "no_data": 1,
            "parse_failure": 2,
        }
        by_case = {r["case_id"]: r["failure_type"] for r in report.failure_records}
        assert by_case == {
            "fail_parse": "parse_failure",
            "fail_nodata": "no_data",
            "fail_halluc": "hallucination",
            "strat_rumor_miss": "parse_failure",
        }

    def test_default_benchmark_carries_failure_stats(self):
        """默认 38 用例：唯一确定性失败为有意 miss 的 rumor case（PARSE_FAILURE）"""
        report = Benchmark().run()
        assert report.failure_stats.get("parse_failure", 0) >= 1
        assert any(r["case_id"] == "cursor_rumor_miss_2026" for r in report.failure_records)
        # 全量 accuracy 命中（mock 确定性）→ 无 accuracy 侧失败
        assert report.accuracy.field_accuracy == 1.0

    def test_markdown_includes_failure_distribution(self, tmp_path):
        report = Benchmark().run()
        out = tmp_path / "benchmark.md"
        _write_markdown(report, out)
        text = out.read_text(encoding="utf-8")
        assert "## 失败类型分布（设计文档 31）" in text
        assert "失败样本" in text
        assert "parse_failure" in text

    def test_csv_includes_failure_rows(self, tmp_path):
        report = Benchmark().run()
        out = tmp_path / "benchmark.csv"
        _write_csv(report, out)
        text = out.read_text(encoding="utf-8")
        assert "failure.parse_failure" in text
        assert "failure.total" in text

    def test_to_dict_carries_failure_fields(self):
        report = Benchmark().run()
        d = report.to_dict()
        assert "failure_stats" in d
        assert "failure_records" in d
        assert isinstance(d["failure_records"], list)
