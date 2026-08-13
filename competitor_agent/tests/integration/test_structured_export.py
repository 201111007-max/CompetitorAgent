"""设计文档 28 集成 — 结构化导出 + 定时调度 + 异动告警

用 FakeExtractor + mock_llm 跑真实 analyze：
- analyze 完成后 reports/competitor/<竞品>.json 存在且含 pricing.pricing（画像）；
- run_scheduled 只重爬过期竞品（freshness 内跳过），过期竞品产生告警；
- export_json=False 时行为与现状一致（无 JSON 落盘、无提示注记）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from competitor_agent.config.loader import AppConfig
from competitor_agent.core.alerting import Alert
from competitor_agent.domain_types.observation import Observation, SourceEvidence
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.interfaces.context import SourceContext
from competitor_agent.memory.timeline_memory import TimelineMemory
from competitor_agent.memory import FourLayerMemory


class _CollectSink:
    def __init__(self) -> None:
        self.alerts: list[Alert] = []

    def emit(self, alert: Alert) -> None:
        self.alerts.append(alert)


class _PricingExtractor:
    """可变定价页的采集器：pricing_page 字段可改，模拟两次分析间的价格变化。"""

    source_name = "web_extractor"

    def __init__(self, pricing_page: str) -> None:
        self.pricing_page = pricing_page

    def fetch(self, gap: object, context: SourceContext) -> Observation:
        url = str(context.kwargs.get("url"))
        if str(getattr(gap, "field", "")) == "sentiment":
            text = "Developers love it and recommend it."
        elif "pricing" in url:
            text = self.pricing_page
        else:
            text = "Cursor is an AI code editor."
        return Observation(
            gap_field=str(getattr(gap, "field", "")),
            source=self.source_name,
            raw_text=text,
            evidence=SourceEvidence(source_name=self.source_name, url=url, trust_level=0.9),
        )


def _api(extractor, mock_llm, tmp_path: Path, export_json: bool = True) -> CompetitorAnalysisAPI:
    cfg = AppConfig()
    cfg.report.output_dir = str(tmp_path / "reports" / "competitor")
    cfg.report.comparison_dir = str(tmp_path / "reports" / "comparison")
    cfg.report.export_json = export_json
    mem = FourLayerMemory(tmp_path / "memory")
    return CompetitorAnalysisAPI(
        extractor=extractor,
        llm=mock_llm,
        use_llm=True,
        max_iterations=10,
        config=cfg,
        memory=mem,
        timeline=TimelineMemory(tmp_path / "timeline"),
    )


class TestAnalyzeExportsJson:
    def test_competitor_json_written_with_pricing(self, fake_extractor, mock_llm, tmp_path: Path) -> None:
        api = _api(fake_extractor, mock_llm, tmp_path)
        report = api.analyze("Cursor")

        j = tmp_path / "reports" / "competitor" / "cursor.json"
        assert j.exists(), f"JSON 未导出: {j}"
        data = json.loads(j.read_text(encoding="utf-8"))
        assert data["competitor"] == "cursor"
        assert data["terminal_state"]
        assert data["dimensions"], "dimensions 为空"
        assert data["pricing"] and data["pricing"]["plans"], "pricing.profile 缺失"
        assert "> 结构化数据已导出" in report.markdown_report

    def test_export_json_disabled_no_side_effects(self, fake_extractor, mock_llm, tmp_path: Path) -> None:
        api = _api(fake_extractor, mock_llm, tmp_path, export_json=False)
        report = api.analyze("Cursor")
        assert not (tmp_path / "reports" / "competitor" / "cursor.json").exists()
        assert "> 结构化数据已导出" not in report.markdown_report


class TestRunScheduled:
    def test_only_stale_re_crawled(self, fake_extractor, mock_llm, tmp_path: Path) -> None:
        api = _api(fake_extractor, mock_llm, tmp_path)
        api.analyze("Cursor")  # 首次分析：刚归档，freshness 内

        # 刚分析完 → 无过期竞品 → 跳过
        assert api.run_scheduled() == []

        # 强制所有维度过期（TTL=-1 天）→ 只重爬 cursor
        cfg = api._config
        cfg.freshness.dimension_ttl_days = {k: -1 for k in cfg.freshness.dimension_ttl_days}
        sink = _CollectSink()
        refreshed = api.run_scheduled(alert_sink=sink)
        assert [r.competitor.name for r in refreshed] == ["cursor"]

    def test_scheduled_diff_emits_alerts(self, mock_llm, tmp_path: Path) -> None:
        extractor = _PricingExtractor("Pro $20/month\nTeams $40/month\nUltra $60/month")
        api = _api(extractor, mock_llm, tmp_path)
        api.analyze("Cursor")

        # 变更定价页内容 → 重爬后 diff 产异动告警
        extractor.pricing_page = "Pro $25/month\nTeams $40/month\nUltra $60/month"
        cfg = api._config
        cfg.freshness.dimension_ttl_days = {k: -1 for k in cfg.freshness.dimension_ttl_days}
        sink = _CollectSink()
        api.run_scheduled(alert_sink=sink)
        kinds = {a.kind for a in sink.alerts}
        assert kinds, "过期重爬后应有告警"
        assert "price_change" in kinds

    def test_tracked_competitors_from_archive(self, fake_extractor, mock_llm, tmp_path: Path) -> None:
        api = _api(fake_extractor, mock_llm, tmp_path)
        api.analyze("Cursor")
        assert api._tracked_competitors() == ["cursor"]