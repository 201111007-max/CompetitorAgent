"""collector/providers 与 SourceSelector 多源路由单测（设计文档 23）

覆盖：缺口→外部源路由、trust 排序、provider 采集分发、配置开关、成功率进化。
全部用注入的 mock 函数，不触发真实网络。
"""
from __future__ import annotations

import pytest

from competitor_agent.collector.providers import (
    BenchmarkSourceProvider,
    CommunitySourceProvider,
    GithubSourceProvider,
    MarketplaceSourceProvider,
    build_providers,
)
from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.config.loader import CollectorConfig
from competitor_agent.domain_types import Competitor, InfoGap
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError


def _cursor():
    return Competitor(
        name="cursor",
        official_links={
            "home": "https://www.cursor.com",
            "pricing": "https://www.cursor.com/pricing",
            "docs": "https://docs.cursor.com",
        },
        external_refs={
            "github_repo": "getcursor/cursor",
            "marketplace": "https://marketplace.visualstudio.com/items?itemName=Anysphere.cursor",
        },
    )


def _no_refs():
    return Competitor(
        name="codex",
        official_links={"home": "https://openai.com/index/introducing-codex/"},
    )


def _github_provider():
    return GithubSourceProvider(
        stars_fn=lambda repo: f"## {repo}\n- Stars: 100",
        releases_fn=lambda repo, limit: f"## {repo} 版本\n- v1.0 (2026-01-01)",
        commits_fn=lambda repo, days: f"## {repo} 提交\n- 2026-01-01 feat",
    )


def _community_provider(search_fn=None):
    return CommunitySourceProvider(search_fn=search_fn or (lambda q: "HN 讨论: 好评"))


class TestRouting:
    def test_ecosystem_routes_to_github_and_marketplace(self):
        s = SourceSelector(
            providers=[
                _github_provider(),
                MarketplaceSourceProvider(extract_fn=lambda url: f"rating 4.8 at {url}"),
            ]
        )
        cands = s.candidates(InfoGap(field="ecosystem"), _cursor())
        names = [c.source_name for c in cands]
        assert "github_stars" in names
        assert "github_releases" in names
        assert "github_commits" in names
        assert "marketplace" in names

    def test_pricing_excludes_github(self):
        s = SourceSelector(providers=[_github_provider()])
        cands = s.candidates(InfoGap(field="pricing"), _cursor())
        assert all(c.kind == "web" or c.kind == "spa" for c in cands)

    def test_sentiment_routes_to_community(self):
        s = SourceSelector(providers=[_community_provider()])
        cands = s.candidates(InfoGap(field="sentiment"), _cursor())
        assert any(c.kind == "social" for c in cands)

    def test_no_refs_no_external_candidates(self):
        s = SourceSelector(providers=[_github_provider()])
        cands = s.candidates(InfoGap(field="ecosystem"), _no_refs())
        assert all(c.kind in ("web", "spa") for c in cands)

    def test_trust_order_official_over_github_over_community(self):
        s = SourceSelector(providers=[_github_provider(), _community_provider()])
        cands = s.candidates(InfoGap(field="feature"), _cursor())
        assert cands[0].trust_level >= 0.9
        github = [c for c in cands if c.kind == "github"]
        assert github, "feature 缺口应含 github 候选"
        assert all(c.trust_level == 0.85 for c in github)

    def test_success_rate_boost_and_tried_removal(self):
        s = SourceSelector(providers=[_github_provider()])
        s.set_success_rates({"github_releases": 1.0})
        gap = InfoGap(field="ecosystem")
        gap.record_source_try("github_stars")
        cands = s.candidates(gap, _cursor())
        names = [c.source_name for c in cands]
        assert "github_stars" not in names
        boosted = next(c for c in cands if c.source_name == "github_releases")
        assert boosted.trust_level == 1.0

    def test_spa_fallback_only_for_official_web(self):
        s = SourceSelector(providers=[_github_provider()])
        cands = s.candidates(InfoGap(field="ecosystem"), _cursor())
        assert any(c.kind == "spa" for c in cands)

    def test_performance_routes_benchmark_before_spa_fallback(self):
        s = SourceSelector(
            providers=[BenchmarkSourceProvider(extract_fn=lambda url: f"| cursor | 62% |")]
        )
        cands = s.candidates(InfoGap(field="performance"), _cursor())
        bench = [c for c in cands if c.kind == "benchmark"]
        assert bench and bench[0].source_name == "benchmark_board"
        assert bench[0].trust_level == 0.9  # 榜单优先（分析器合并时同指标以榜单为准）
        spa = next(c for c in cands if c.kind == "spa")
        assert cands.index(bench[0]) < cands.index(spa)

    def test_performance_without_benchmark_falls_back_to_web(self):
        s = SourceSelector(providers=[])
        cands = s.candidates(InfoGap(field="performance"), _cursor())
        assert cands and cands[0].kind == "web"


class TestProviders:
    def test_github_fetch_wraps_observation(self):
        p = _github_provider()
        competitor = _cursor()
        cand = p.candidates(InfoGap(field="ecosystem"), competitor)[0]
        obs = p.fetch(InfoGap(field="ecosystem"), cand, competitor)
        assert "Stars: 100" in obs.raw_text
        assert obs.evidence.url == cand.url
        assert obs.evidence.trust_level == 0.85

    def test_github_failure_raises_unavailable(self):
        p = GithubSourceProvider(stars_fn=lambda repo: "⚠ 仓库不存在")
        competitor = _cursor()
        cand = p.candidates(InfoGap(field="ecosystem"), competitor)[0]
        with pytest.raises(DataSourceUnavailableError):
            p.fetch(InfoGap(field="ecosystem"), cand, competitor)

    def test_marketplace_fetch(self):
        p = MarketplaceSourceProvider(extract_fn=lambda url: f"rating 4.8 at {url}")
        competitor = _cursor()
        cand = p.candidates(InfoGap(field="ecosystem"), competitor)[0]
        obs = p.fetch(InfoGap(field="ecosystem"), cand, competitor)
        assert "rating 4.8" in obs.raw_text

    def test_community_requires_search_fn(self):
        inactive = CommunitySourceProvider()
        assert not inactive.supports(InfoGap(field="sentiment"), _cursor())
        active = CommunitySourceProvider(search_fn=lambda q: "HN: 好评")
        assert active.supports(InfoGap(field="sentiment"), _cursor())


class TestBuildProviders:
    def test_default_master_off_returns_empty(self):
        assert build_providers() == []
        assert build_providers(CollectorConfig(enable_external_sources=False)) == []

    def test_master_on_builds_all_enabled_kinds(self):
        cfg = CollectorConfig(enable_external_sources=True)
        providers = build_providers(cfg)
        kinds = {p.kind for p in providers}
        assert {"github", "marketplace", "social"} <= kinds

    def test_per_kind_switch_respected(self):
        cfg = CollectorConfig(
            enable_external_sources=True,
            enable_github=True,
            enable_marketplace=False,
            enable_community=False,
            enable_benchmark=False,
        )
        providers = build_providers(cfg)
        assert {p.kind for p in providers} == {"github"}

    def test_benchmark_enabled_by_default_with_master_on(self):
        cfg = CollectorConfig(enable_external_sources=True)
        providers = build_providers(cfg)
        assert "benchmark" in {p.kind for p in providers}
