"""设计文档 26 §5 单测（timeline）：diff 事件类型 / 同值防噪声 / 落盘持久化 / 渲染"""
from __future__ import annotations

from competitor_agent.core.markdown_renderer import MarkdownRenderer
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.observation import SourceEvidence
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult
from competitor_agent.memory.timeline_memory import TimelineEvent, TimelineMemory

URL = "https://example.test/pricing"


def _report(name: str, dims: dict[str, tuple[str, object]]) -> CompetitorReport:
    results = [
        DimensionResult(
            dimension=dim_name,
            summary=str(summary),
            details=details,
            confidence=0.9,
            timestamp=f"2026-08-0{d}",
            evidence=[
                SourceEvidence(
                    source_name=f"src_{dim_name}",
                    url=URL,
                    access_time=f"2026-08-0{d}T00:00:00+00:00",
                )
            ],
        )
        for d, (dim_name, (summary, details)) in enumerate(dims.items(), 1)
    ]
    return CompetitorReport(competitor=Competitor(name=name), dimension_results=results)


_PREV = _report(
    "cursor",
    {
        "pricing": ("price $20", {"plans": [{"name": "Pro", "price": "20"}]}),
        "feature": ("feature 5", {"features": [f"f{i}" for i in range(5)]}),
        "performance": ("score 60%", {"benchmarks": {"swe": 60}}),
    },
)

_NEXT = _report(
    "cursor",
    {
        "pricing": ("price $40", {"plans": [{"name": "Pro", "price": "40"}]}),
        "feature": ("feature 6", {"features": [f"f{i}" for i in range(6)]}),
        "performance": ("score 63%", {"benchmarks": {"swe": 63}}),
    },
)


class TestTimelineDiff:
    def test_three_change_types(self) -> None:
        events = TimelineMemory.diff(_PREV, _NEXT)
        types = {e.event_type for e in events}
        assert types == {"price_change", "feature_added", "score_change"}
        assert len(events) == 3

    def test_events_carry_evidence_urls(self) -> None:
        events = TimelineMemory.diff(_PREV, _NEXT)
        for e in events:
            assert e.competitor == "cursor"
            assert e.evidence_urls and URL in e.evidence_urls
            assert e.occurred_at
            assert e.diff_from  # 与上一次的对比基线（上一轮时间戳前缀）

    def test_same_values_no_event(self) -> None:
        assert TimelineMemory.diff(_PREV, _PREV) == []

    def test_new_dimension_no_baseline_no_event(self) -> None:
        only_new = _report("cursor", {"roadmap": ("new", {})})
        assert TimelineMemory.diff(_PREV, only_new) == []

    def test_dimension_event_type_map(self) -> None:
        events = TimelineMemory.diff(_PREV, _NEXT)
        by_type = {e.event_type: e for e in events}
        assert by_type["price_change"].summary
        assert by_type["score_change"].diff_from[:10]  # ISO 日期前缀


class TestTimelineMemory:
    def test_update_records_events_and_snapshot(self, tmp_path) -> None:
        tl = TimelineMemory(tmp_path / "memory")
        assert tl.update(_PREV) == []  # 首轮无基线，不产生事件
        events = tl.update(_NEXT)
        assert len(events) == 3
        # 已落盘，可跨实例读取
        tl2 = TimelineMemory(tmp_path / "memory")
        assert len(tl2.events("cursor")) == 3
        assert tl2.last_analyzed_at("cursor") == _NEXT.created_at

    def test_events_sorted_and_limited(self, tmp_path) -> None:
        tl = TimelineMemory(tmp_path / "memory")
        for i in range(5):
            tl.append(TimelineEvent(competitor="cursor", event_type="version_release", summary=f"v{i}", occurred_at=f"2026-08-0{i}T00:00:00+00:00"))
        got = tl.events("cursor", limit=3)
        assert len(got) == 3
        assert got[0].summary == "v4"  # 新的在前
        assert tl.events("cursor", limit=10)[-1].summary == "v0"

    def test_append_persists(self, tmp_path) -> None:
        tl = TimelineMemory(tmp_path / "memory")
        tl.append(TimelineEvent(competitor="cursor", event_type="price_change", summary="涨到 40 刀"))
        events = tl.events("cursor")
        assert events[0].event_type == "price_change"

    def test_render_timeline_section(self) -> None:
        events = TimelineMemory.diff(_PREV, _NEXT)
        md = MarkdownRenderer().render_timeline(events)
        assert "## 竞品时间线" in md
        assert "price_change" in md
        assert "| 日期 | 类型 | 变化 | 证据 |" in md

    def test_render_timeline_empty(self) -> None:
        assert MarkdownRenderer().render_timeline([]) == ""