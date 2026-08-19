"""设计文档 26 §5 集成：analyze 两次 → 报告含新鲜度 + 「## 竞品时间线」段落，事件带日期与证据 URL"""
from __future__ import annotations

import pytest

from competitor_agent.config.loader import AppConfig, CollectorConfig
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.memory import FourLayerMemory, TimelineMemory
from tests.conftest import FakeExtractor

pytestmark = pytest.mark.integration

# 离线环境 URL 守卫（DNS 解析）会拦截 before 采集器运行：关闭守卫让采集器真被命中
_OFFLINE_CFG = AppConfig(collector=CollectorConfig(block_private_urls=False))


class ShiftPricingExtractor(FakeExtractor):
    """价格文本随调用次数漂移，模拟"竞品改价"跨时间变化。

    doc 49：web_extract 传 InfoGap(field="web")，按 URL 判定定价页而非 gap.field。
    """

    def __init__(self, pricing_texts: list[str]) -> None:
        super().__init__()
        self._texts = list(pricing_texts)
        self._i = 0

    def fetch(self, gap, context):
        obs = super().fetch(gap, context)
        if "pricing" in str(context.kwargs.get("url")):
            obs.raw_text = self._texts[self._i % len(self._texts)]
            self._i += 1
        return obs


class TestFreshnessAndTimelineIntegration:
    def test_analyze_twice_produces_timeline(self, mock_llm, tmp_path) -> None:
        mem = FourLayerMemory(tmp_path / "memory")
        tl = TimelineMemory(tmp_path / "timeline")
        extractor = ShiftPricingExtractor(
            ["Pro $20/month\nTeams $40/month", "Pro $40/month\nTeams $60/month"]
        )
        api = CompetitorAnalysisAPI(
            llm=mock_llm,
            use_llm=True,
            extractor=extractor,
            memory=mem,
            timeline=tl,
            max_iterations=10,
            config=_OFFLINE_CFG,
        )

        r1 = api.analyze("分析 Cursor", mode="single", session_id="sess_tl_1")
        r2 = api.analyze("分析 Cursor", mode="single", session_id="sess_tl_2")

        # 新鲜度元数据（设计文档 26 §2.1）
        assert r1.freshness is not None
        assert "数据新鲜度" in r1.markdown_report
        assert "pricing" in r1.freshness.dimension_ages

        # 二次分析出现价格变化时间线
        assert "## 竞品时间线" in r2.markdown_report, r2.markdown_report
        events = tl.events("cursor")
        assert events, "应产生时间线事件"
        price = [e for e in events if e.event_type == "price_change"]
        assert price, [e.event_type for e in events]
        assert price[0].evidence_urls, "事件应带证据 URL"
        assert price[0].occurred_at, "事件应带日期"

        # 归档会话带 freshness → refresh_stale 可判定过期
        sessions = mem.list_sessions("cursor")
        assert sessions
        assert sessions[0].raw.get("freshness") is not None

    def test_first_analysis_no_timeline_no_error(self, mock_llm, tmp_path) -> None:
        """回归：首次分析无基线，不产生 diff、不报错（用隔离时间线避免共享快照）。"""
        tl = TimelineMemory(tmp_path / "timeline_isolated")
        api = CompetitorAnalysisAPI(
            llm=mock_llm,
            use_llm=True,
            extractor=FakeExtractor(),
            timeline=tl,
            max_iterations=10,
            config=_OFFLINE_CFG,
        )
        report = api.analyze("分析 Cursor", mode="single", session_id="sess_tl_first")
        assert "## 竞品时间线" not in report.markdown_report
        assert tl.events("cursor") == []
        assert report.terminal_state in ("success", "partial")

    def test_team_path_also_records_timeline(self, mock_llm, tmp_path) -> None:
        mem = FourLayerMemory(tmp_path / "memory")
        tl = TimelineMemory(tmp_path / "timeline")
        extractor = ShiftPricingExtractor(
            ["Pro $20/month\nTeams $40/month", "Pro $40/month\nTeams $60/month"]
        )
        api = CompetitorAnalysisAPI(
            llm=mock_llm,
            use_llm=True,
            extractor=extractor,
            memory=mem,
            timeline=tl,
            max_iterations=10,
            config=_OFFLINE_CFG,
        )
        api.analyze("分析 Cursor", mode="team", session_id="sess_tl_t1")
        api.analyze("分析 Cursor", mode="team", session_id="sess_tl_t2")
        events = tl.events("cursor")
        assert events
        assert any(e.event_type == "price_change" for e in events)