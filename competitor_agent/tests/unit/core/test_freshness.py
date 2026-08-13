"""设计文档 26 §5 单测（freshness）：年龄计算 / stale 维度 / markdown_note / 序列化 / stale_under_ttl"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from competitor_agent.config.loader import AppConfig, FreshnessConfig, load_config
from competitor_agent.core.markdown_renderer import MarkdownRenderer
from competitor_agent.domain_types.freshness import DEFAULT_TTL_DAYS, ReportFreshness, stale_under_ttl
from competitor_agent.domain_types.observation import SourceEvidence
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult


def _result(dim: str, access_time: datetime, price: str = "10") -> DimensionResult:
    return DimensionResult(
        dimension=dim,
        summary=f"{dim}: {price}",
        details={"plan": price},
        confidence=0.9,
        timestamp=access_time.isoformat(),
        evidence=[SourceEvidence(source_name=f"src_{dim}", url=f"https://{dim}.test", access_time=access_time.isoformat())],
    )


_NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)


class TestReportFreshness:
    def test_age_and_stale_dimensions(self) -> None:
        fresh = ReportFreshness.from_results(
            [_result("pricing", _NOW - timedelta(days=9)), _result("feature", _NOW - timedelta(days=1))],
            ttl_days=DEFAULT_TTL_DAYS,
            now=_NOW,
        )
        assert fresh.dimension_ages["pricing"] == 9.0
        assert fresh.dimension_ages["feature"] == 1.0
        assert fresh.stale_dimensions == ["pricing"]
        assert fresh.source_retrieved_at["pricing"] == (_NOW - timedelta(days=9)).isoformat()

    def test_no_evidence_timestamps_not_stale(self) -> None:
        r = DimensionResult(dimension="roadmap", summary="s")
        fresh = ReportFreshness.from_results([r], now=_NOW)
        assert fresh.dimension_ages == {}
        assert fresh.stale_dimensions == []

    def test_markdown_note_has_stale_hint(self) -> None:
        fresh = ReportFreshness.from_results([_result("pricing", _NOW - timedelta(days=9))], now=_NOW)
        note = fresh.markdown_note()
        assert "数据可能过期" in note
        assert "re-analyze" in note
        assert "pricing" in note

    def test_markdown_note_plain_without_stale(self) -> None:
        fresh = ReportFreshness.from_results([_result("feature", _NOW - timedelta(days=1))], now=_NOW)
        note = fresh.markdown_note()
        assert "数据新鲜度" in note
        assert "数据可能过期" not in note

    def test_ttl_override_affects_stale(self) -> None:
        fresh = ReportFreshness.from_results([_result("pricing", _NOW - timedelta(days=5))], ttl_days={"pricing": 3}, now=_NOW)
        assert "pricing" in fresh.stale_dimensions

    def test_to_dict_from_dict_roundtrip(self) -> None:
        fresh = ReportFreshness.from_results([_result("pricing", _NOW - timedelta(days=9))], now=_NOW)
        assert ReportFreshness.from_dict(fresh.to_dict()) == fresh
        assert ReportFreshness.from_dict(None) is None

    def test_render_includes_freshness_note(self) -> None:
        report = CompetitorReport(competitor=_competitor("cursor"), dimension_results=[_result("feature", _NOW - timedelta(days=1))])
        report.freshness = ReportFreshness.from_results(report.dimension_results, now=_NOW)
        md = MarkdownRenderer().render(report)
        assert "数据新鲜度" in md
        assert "## 维度结论" in md


class TestStaleUnderTTL:
    def test_from_stored_freshness_ages(self) -> None:
        raw = {
            "created_at": _NOW.isoformat(),
            "freshness": ReportFreshness.from_results(
                [_result("pricing", _NOW - timedelta(days=99))], now=_NOW
            ).to_dict(),
        }
        assert stale_under_ttl(raw, ttl_days=DEFAULT_TTL_DAYS, now=_NOW) == ["pricing"]

    def test_ttl_override_recomputes_stored_ages(self) -> None:
        raw = {
            "created_at": _NOW.isoformat(),
            "freshness": ReportFreshness.from_results(
                [_result("feature", _NOW - timedelta(days=20))], now=_NOW
            ).to_dict(),
        }
        # 默认 feature TTL=30 不过期；覆盖为 10 后过期
        assert stale_under_ttl(raw, ttl_days={"feature": 10}, now=_NOW) == ["feature"]

    def test_fallback_old_created_at_marks_all_stale(self) -> None:
        raw = {"created_at": (_NOW - timedelta(days=365)).isoformat()}
        assert stale_under_ttl(raw, ttl_days=DEFAULT_TTL_DAYS, now=_NOW) == sorted(DEFAULT_TTL_DAYS)

    def test_fallback_fresh_created_at_no_stale(self) -> None:
        raw = {"created_at": _NOW.isoformat()}
        assert stale_under_ttl(raw, ttl_days=DEFAULT_TTL_DAYS, now=_NOW) == []

    def test_invalid_created_at_returns_empty(self) -> None:
        assert stale_under_ttl({"created_at": "nope"}, ttl_days=DEFAULT_TTL_DAYS, now=_NOW) == []


class TestFreshnessConfigParsing:
    def test_default_config(self) -> None:
        cfg = AppConfig()
        assert isinstance(cfg.freshness, FreshnessConfig)
        assert cfg.freshness.dimension_ttl_days["pricing"] == 7
        assert cfg.freshness.refresh_check_enabled is True

    def test_yaml_section_parsed(self, tmp_path) -> None:
        path = tmp_path / "cfg.yaml"
        path.write_text(
            "freshness:\n  dimension_ttl_days:\n    pricing: 2\n    roadmap: 90\n  refresh_check_enabled: false\n",
            encoding="utf-8",
        )
        cfg = load_config(path)
        assert cfg.freshness.dimension_ttl_days["pricing"] == 2
        assert cfg.freshness.dimension_ttl_days["roadmap"] == 90
        assert cfg.freshness.refresh_check_enabled is False
        # 未在 YAML 中给出的维度用默认
        assert cfg.freshness.dimension_ttl_days["feature"] == 30


def _competitor(name: str):
    from competitor_agent.domain_types.competitor import Competitor

    return Competitor(name=name)