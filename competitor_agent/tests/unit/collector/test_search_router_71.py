"""设计文档 71 §3.3/§4.1 — DDG 免费主力 + SearchRouter 降级池 + build_search_router 门控。

覆盖（§9 验收）：DDG 正常解析（MockTransport + 跳转链接还原）/ 限流 202-anomaly / 429 /
网络 5xx / 4xx / 解析失败 kind；SearchRouter 主力命中即返、降级池接管（via 标注）、全失败
抛 SearchError；build_search_router enable_external_sources 门控 + tavily 缺 Key 回落 DDG。
"""
from __future__ import annotations

import httpx
import pytest

from competitor_agent.collector.search import (
    SearchError,
    SearchHit,
    SearchRouter,
    TavilySearchProvider,
    build_search_provider,
    build_search_router,
)
from competitor_agent.collector.search_providers.ddg import DuckDuckGoSearchProvider
from competitor_agent.config.loader import CollectorConfig

_DDG_HTML = """<html><body>
<div class="result">
  <h2 class="result__title"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fcursor.com%2Fpricing&amp;rut=abc">Cursor Pricing</a></h2>
  <div class="result__snippet">AI code editor pricing page</div>
</div>
<div class="result">
  <a class="result__a" href="https://windsurf.com">Windsurf</a>
  <div class="result__snippet">agentic IDE</div>
</div>
</body></html>"""


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _html_client(html: str = _DDG_HTML, status: int = 200) -> httpx.Client:
    return _client(lambda request: httpx.Response(status, text=html))


class TestDuckDuckGoProvider:
    def test_parses_hits_and_decodes_redirect_link(self):
        p = DuckDuckGoSearchProvider(client=_html_client())
        hits = p.search("cursor")
        assert hits[0].title == "Cursor Pricing"
        assert hits[0].url == "https://cursor.com/pricing"  # /l/?uddg= 还原
        assert hits[0].snippet == "AI code editor pricing page"
        assert hits[1].url == "https://windsurf.com"

    def test_source_engine_class_attr(self):
        assert DuckDuckGoSearchProvider.source_engine == "duckduckgo"

    def test_202_anomaly_rate_limited(self):
        p = DuckDuckGoSearchProvider(client=_html_client(status=202))
        with pytest.raises(SearchError) as ei:
            p.search("x")
        assert ei.value.kind == "rate_limited"

    def test_429_rate_limited(self):
        p = DuckDuckGoSearchProvider(client=_client(lambda r: httpx.Response(429)))
        with pytest.raises(SearchError) as ei:
            p.search("x")
        assert ei.value.kind == "rate_limited"

    def test_5xx_network(self):
        p = DuckDuckGoSearchProvider(client=_client(lambda r: httpx.Response(503)))
        with pytest.raises(SearchError) as ei:
            p.search("x")
        assert ei.value.kind == "network"

    def test_4xx_http(self):
        p = DuckDuckGoSearchProvider(client=_client(lambda r: httpx.Response(403)))
        with pytest.raises(SearchError) as ei:
            p.search("x")
        assert ei.value.kind == "http"

    def test_connect_error_network(self):
        def handler(request):
            raise httpx.ConnectError("boom")

        p = DuckDuckGoSearchProvider(client=_client(handler))
        with pytest.raises(SearchError) as ei:
            p.search("x")
        assert ei.value.kind == "network"

    def test_empty_results(self):
        p = DuckDuckGoSearchProvider(client=_html_client("<html><body></body></html>"))
        assert p.search("nothing") == []


class _FakeProvider:
    """可脚本化的 provider：命中/抛错/空 由构造参数决定。"""

    def __init__(self, hits=None, error=None, engine="fake"):
        self._hits = hits
        self._error = error
        self.source_engine = engine
        self.calls = 0

    def search(self, query, max_results=8):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return list(self._hits or [])


class TestSearchRouter:
    def test_primary_hits_returned_and_stamped(self):
        primary = _FakeProvider(
            [SearchHit("A", "https://a.com", "s")], engine="duckduckgo"
        )
        router = SearchRouter([primary])
        hits = router.search("q")
        assert len(hits) == 1
        assert hits[0].source_engine == "duckduckgo"
        assert hits[0].fetched_at > 0
        assert primary.calls == 1  # 主力命中不触发降级

    def test_primary_error_falls_back_to_tavily(self):
        primary = _FakeProvider(error=SearchError("ddg 挂了", kind="rate_limited"), engine="duckduckgo")
        tavily = _FakeProvider([SearchHit("B", "https://b.com", "s")], engine="tavily")
        router = SearchRouter([primary, tavily])
        hits = router.search("q")
        assert hits[0].url == "https://b.com"
        assert hits[0].source_engine == "tavily"  # via: tavily
        assert primary.calls == 1 and tavily.calls == 1

    def test_primary_empty_falls_back(self):
        primary = _FakeProvider(hits=[], engine="duckduckgo")
        tavily = _FakeProvider([SearchHit("B", "https://b.com", "s")], engine="tavily")
        hits = SearchRouter([primary, tavily]).search("q")
        assert hits and hits[0].source_engine == "tavily"

    def test_all_error_raises_last(self):
        router = SearchRouter(
            [
                _FakeProvider(error=SearchError("1", kind="network"), engine="duckduckgo"),
                _FakeProvider(error=SearchError("2", kind="rate_limited"), engine="tavily"),
            ]
        )
        with pytest.raises(SearchError) as ei:
            router.search("q")
        assert ei.value.kind == "rate_limited"

    def test_all_empty_returns_empty(self):
        router = SearchRouter([_FakeProvider(hits=[], engine="duckduckgo")])
        assert router.search("q") == []


class TestBuildSearchRouter:
    def test_gated_by_enable_external_sources(self):
        assert build_search_router(CollectorConfig(enable_external_sources=False)) is None

    def test_duckduckgo_default(self):
        router = build_search_router(
            CollectorConfig(enable_external_sources=True, search_provider="duckduckgo")
        )
        assert isinstance(router, SearchRouter)
        assert router._providers[0].source_engine == "duckduckgo"

    def test_tavily_with_key_primary(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
        router = build_search_router(
            CollectorConfig(enable_external_sources=True, search_provider="tavily")
        )
        assert isinstance(router._providers[0], TavilySearchProvider)

    def test_tavily_without_key_falls_back_to_ddg(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        router = build_search_router(
            CollectorConfig(enable_external_sources=True, search_provider="tavily")
        )
        assert router._providers[0].source_engine == "duckduckgo"

    def test_tavily_key_adds_fallback_pool(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
        router = build_search_router(
            CollectorConfig(enable_external_sources=True, search_provider="duckduckgo")
        )
        engines = [p.source_engine for p in router._providers]
        assert engines == ["duckduckgo", "tavily"]

    def test_unknown_provider_falls_back_to_ddg(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        router = build_search_router(
            CollectorConfig(enable_external_sources=True, search_provider="bocha")
        )
        assert router._providers[0].source_engine == "duckduckgo"


class TestCompatBackward:
    """决策⑥：build_search_provider 行为与 doc 66 逐位一致（兼容薄包装）。"""

    def test_search_provider_unchanged(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        assert build_search_provider(CollectorConfig(search_provider="tavily")) is None
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
        assert build_search_provider(CollectorConfig(search_provider="tavily")) is not None
        assert build_search_provider(CollectorConfig(search_provider="")) is None
