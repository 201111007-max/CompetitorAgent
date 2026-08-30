"""report_exporter 单测（设计文档 28 §5 导出 schema）：
report_to_dict 稳定 schema（schema_version/competitor/dimensions/evidence/freshness/
pricing.pricing/benchmark_scores）、JSON 可解析、原子写无 .tmp 残留；比较矩阵导出对齐
维度×竞品 + best_per_dimension。"""
from __future__ import annotations

import json
from pathlib import Path

from competitor_agent.core import report_exporter as re
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.freshness import ReportFreshness
from competitor_agent.domain_types.observation import SourceEvidence
from competitor_agent.domain_types.report import ComparisonReport, CompetitorReport, DimensionResult


def _evidence(url: str = "https://cursor.com/pricing", trust: float = 0.9) -> list[SourceEvidence]:
    return [SourceEvidence(source_name="web_extractor", url=url, trust_level=trust)]


def _dimension(
    field: str,
    summary: str,
    details: dict,
    confidence: float = 0.8,
    status: str = "complete",
) -> DimensionResult:
    from competitor_agent.domain_types.enums import ResultStatus

    return DimensionResult(
        dimension=field,
        summary=summary,
        details=details,
        confidence=confidence,
        evidence=_evidence(),
        status=ResultStatus(status),
    )


def _pricing_report(name: str = "cursor") -> CompetitorReport:
    pricing = {
        "plans": [{"tier": "pro", "monthly_price_usd": 20, "period": "month"}],
        "usage": {"unit": "request", "per_unit_usd": 0.0005, "included_units": 1000},
        "cost_scenarios": {"light": 1.0, "medium": 2.0},
    }
    return CompetitorReport(
        competitor=Competitor(name=name),
        dimension_results=[
            _dimension(
                "pricing",
                "Pro $20/mo + 按量计费",
                {"pricing": pricing, **pricing},
            ),
            _dimension(
                "performance",
                "榜单数据",
                {"benchmarks": [{"name": "swe_bench_verified", "score": 62.0, "board": "swe_bench"}]},
                confidence=0.9,
            ),
        ],
        overall_score=0.8,
        overall_confidence=0.85,
        terminal_state="success",
        freshness=ReportFreshness(
            dimension_ages={"pricing": 1.5, "performance": 3.0},
            stale_dimensions=[],
        ),
    )


class TestReportToDict:
    def test_schema_fields_present(self) -> None:
        data = re.report_to_dict(_pricing_report())
        assert data["schema_version"] == re.REPORT_SCHEMA_VERSION
        assert data["competitor"] == "cursor"
        assert data["terminal_state"] == "success"
        assert data["created_at"]
        assert set(data) >= {
            "schema_version", "competitor", "terminal_state", "created_at",
            "dimensions", "freshness", "pricing", "benchmark_scores", "gaps_pending",
        }

    def test_dimensions_and_evidence_shape(self) -> None:
        data = re.report_to_dict(_pricing_report())
        dims = {d["field"]: d for d in data["dimensions"]}
        assert set(dims) == {"pricing", "performance"}
        p = dims["pricing"]
        assert p["status"] == "complete"
        assert p["confidence"] == 0.8
        assert p["summary"]
        assert p["evidence"] == [{"url": "https://cursor.com/pricing", "trust": 0.9}]

    def test_pricing_profile_embedded(self) -> None:
        data = re.report_to_dict(_pricing_report())
        assert data["pricing"]["plans"][0]["tier"] == "pro"
        assert data["pricing"]["cost_scenarios"]["light"] == 1.0

    def test_benchmark_scores_extracted(self) -> None:
        data = re.report_to_dict(_pricing_report())
        assert data["benchmark_scores"][0]["name"] == "swe_bench_verified"
        assert data["benchmark_scores"][0]["score"] == 62.0

    def test_freshness_serialized(self) -> None:
        data = re.report_to_dict(_pricing_report())
        assert data["freshness"]["dimension_ages"]["pricing"] == 1.5
        assert data["freshness"]["stale_dimensions"] == []

    def test_no_pricing_reports_none(self) -> None:
        report = CompetitorReport(
            competitor=Competitor(name="x"),
            dimension_results=[_dimension("feature", "功能", {"features": ["a"]})],
        )
        data = re.report_to_dict(report)
        assert data["pricing"] is None
        assert data["benchmark_scores"] == []

    def test_json_serializable_roundtrip(self, tmp_path: Path) -> None:
        path = re.export_competitor_json(_pricing_report(), output_dir=tmp_path)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["competitor"] == "cursor"
        assert loaded["schema_version"] == "1.0.0"


class TestExportCompetitorJson:
    def test_writes_file_at_same_dir(self, tmp_path: Path) -> None:
        path = re.export_competitor_json(_pricing_report(), output_dir=tmp_path)
        assert path == tmp_path / "cursor.json"
        assert path.exists()

    def test_atomic_no_tmp_leftover(self, tmp_path: Path) -> None:
        re.export_competitor_json(_pricing_report(), output_dir=tmp_path)
        re.export_competitor_json(_pricing_report(), output_dir=tmp_path)
        leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp" or ".tmp" in p.name]
        assert leftovers == []

    def test_sanitized_filename(self, tmp_path: Path) -> None:
        path = re.export_competitor_json(_pricing_report(name="../../evil"), output_dir=tmp_path)
        assert path.parent == tmp_path
        assert ".." not in path.name


class TestExportComparisonJson:
    def _comparison(self) -> ComparisonReport:
        a = _pricing_report("cursor")
        b = _pricing_report("windsurf")
        b.dimension_results[1].confidence = 0.5  # windsurf 榜单位置更低
        return ComparisonReport(competitors=[a.competitor, b.competitor], reports=[a, b])

    def test_matrix_dims_x_competitors(self, tmp_path: Path) -> None:
        path = re.export_comparison_json(self._comparison(), output_dir=tmp_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["competitors"] == ["cursor", "windsurf"]
        matrix = {row["dimension"]: row for row in data["matrix"]}
        assert set(matrix) == {"pricing", "performance"}
        row = matrix["pricing"]
        assert set(row["values"]) == {"cursor", "windsurf"}
        assert row["best"] in ("cursor", "windsurf")

    def test_best_per_dimension_included(self, tmp_path: Path) -> None:
        path = re.export_comparison_json(self._comparison(), output_dir=tmp_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        perf = data["best_per_dimension"]["performance"]
        assert perf["competitor"] == "cursor"
        assert perf["confidence"] == 0.9

    def test_comparison_filename(self, tmp_path: Path) -> None:
        path = re.export_comparison_json(self._comparison(), output_dir=tmp_path)
        assert path.name == "cursor___windsurf.json"
        assert path.exists()

    def test_default_writes_to_comparison_subdir(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        """设计文档 70 §8.2 D2a：默认（output_dir=None）→ resolve_comparison_dir()，不再写主目录。"""
        from competitor_agent.core import report_archiver as ra

        monkeypatch.setattr(ra, "get_setting", lambda *a, **k: "")
        base = ra.resolve_output_dir(None)
        path = re.export_comparison_json(self._comparison())
        assert path.parent == base / "comparison"
        assert path.exists()