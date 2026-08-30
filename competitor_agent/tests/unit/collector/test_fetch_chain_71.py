"""设计文档 71 §3.4/§4.2/§4.3 — 抓取三级降级链 + _is_shell + 各 provider + build_fetch_router。

覆盖（§9 验收）：trafilatura 提取（真实库，importorskip）/ jina 云端兜底（MockTransport，
有无 Key 的 Authorization）/ crawl4ai 浏览器渲染（注入 fake crawl4ai 模块）/ 隐性失败
_is_shell 触发降级 / 三级全败 reason / build_fetch_router FETCH_ENABLED=false → None。
"""
from __future__ import annotations

import sys

import httpx
import pytest

from competitor_agent.collector.fetch import (
    FetchResult,
    FetchRouter,
    build_fetch_router,
)
from competitor_agent.collector.fetch_policy import _is_shell
from competitor_agent.config.loader import CollectorConfig

_LONG_TEXT = "这是足够长的正文内容用于通过空壳检测。" * 20


class _FakeProvider:
    def __init__(self, result=None, error=None, level="fake", available=True):
        self._result = result
        self._error = error
        self.source_provider = level
        self._available = available
        self.calls = 0

    def available(self):
        return self._available

    def fetch(self, url, max_chars):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._result


class TestIsShell:
    def test_empty_is_shell(self):
        assert _is_shell("")
        assert _is_shell("   ")

    def test_short_is_shell(self):
        assert _is_shell("短" * 30)  # < 80 字符

    def test_anti_bot_is_shell(self):
        assert _is_shell("please enable javascript 后继续" + "x" * 100)
        assert _is_shell("captcha 验证" + "y" * 100)
        assert _is_shell("Access Denied" + "z" * 100)

    def test_normal_not_shell(self):
        assert not _is_shell(_LONG_TEXT)


class TestFetchRouter:
    def _ok(self, content=_LONG_TEXT, level="trafilatura"):
        return FetchResult(success=True, url="u", content=content, provider=level)

    def test_level1_success_returns(self):
        p1 = _FakeProvider(self._ok(), level="trafilatura")
        p2 = _FakeProvider(self._ok(level="jina"), level="jina")
        router = FetchRouter([p1, p2])
        result = router.fetch("https://x.com", 8000)
        assert result.success and result.provider == "trafilatura"
        assert p2.calls == 0  # 命中即停

    def test_shell_triggers_degradation(self):
        p1 = _FakeProvider(self._ok(content="短" * 30), level="trafilatura")  # 空壳
        p2 = _FakeProvider(self._ok(content=_LONG_TEXT, level="jina"), level="jina")
        result = FetchRouter([p1, p2]).fetch("u", 8000)
        assert result.provider == "jina"  # via: jina（隐性失败 → 下一级）

    def test_hard_failure_degrades(self):
        p1 = _FakeProvider(
            FetchResult(success=False, url="u", reason="HTTP 403"), level="trafilatura"
        )
        p2 = _FakeProvider(self._ok(level="jina"), level="jina")
        result = FetchRouter([p1, p2]).fetch("u", 8000)
        assert result.provider == "jina"

    def test_provider_exception_degrades(self):
        p1 = _FakeProvider(error=RuntimeError("crashed"), level="trafilatura")
        p2 = _FakeProvider(self._ok(level="jina"), level="jina")
        result = FetchRouter([p1, p2]).fetch("u", 8000)
        assert result.success and result.provider == "jina"

    def test_all_failed_reason_aggregated(self):
        p1 = _FakeProvider(FetchResult(success=False, url="u", reason="HTTP 403"), level="trafilatura")
        p2 = _FakeProvider(FetchResult(success=False, url="u", reason="限流 429"), level="jina")
        result = FetchRouter([p1, p2]).fetch("u", 8000)
        assert not result.success
        assert "HTTP 403" in result.reason and "限流 429" in result.reason

    def test_unavailable_provider_excluded(self):
        p1 = _FakeProvider(self._ok(), level="trafilatura", available=False)
        p2 = _FakeProvider(self._ok(level="jina"), level="jina")
        router = FetchRouter([p1, p2])
        assert p1.calls == 0  # 构建期不可用，不参与
        assert router.active_count == 1


class TestTrafilaturaProvider:
    def test_extracts_real_html(self):
        pytest.importorskip("trafilatura")
        from competitor_agent.collector.fetch_providers.trafilatura_fetch import (
            TrafilaturaFetchProvider,
        )

        html = (
            "<html><head><title>Cursor Pricing</title></head><body><article>"
            "<h1>Cursor</h1><p>" + ("AI code editor 定价" * 30) + "</p></article></body></html>"
        )

        def handler(request):
            return httpx.Response(200, text=html)

        p = TrafilaturaFetchProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
        result = p.fetch("https://example.com/pricing", 8000)
        assert result.success
        assert result.provider == "trafilatura"
        assert "Cursor" in result.content
        assert len(result.content) <= 8000

    def test_http_error_returns_failure(self):
        pytest.importorskip("trafilatura")
        from competitor_agent.collector.fetch_providers.trafilatura_fetch import (
            TrafilaturaFetchProvider,
        )

        p = TrafilaturaFetchProvider(
            client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
        )
        result = p.fetch("https://example.com/", 8000)
        assert not result.success and "404" in result.reason


class TestJinaProvider:
    def _provider(self, api_key="", handler=None):
        from competitor_agent.collector.fetch_providers.jina_fetch import JinaFetchProvider

        if handler is None:
            handler = lambda r: httpx.Response(200, text=_LONG_TEXT)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        return JinaFetchProvider(api_key=api_key, client=client)

    def test_no_key_no_auth_header(self):
        seen = {}

        def handler(request):
            seen["auth"] = request.headers.get("Authorization")
            seen["url"] = str(request.url)
            return httpx.Response(200, text=_LONG_TEXT)

        result = self._provider(api_key="", handler=handler).fetch("https://example.com/", 8000)
        assert result.success and result.provider == "jina"
        assert seen["auth"] is None
        assert "https://r.jina.ai/https://example.com/" in seen["url"]

    def test_key_sends_bearer(self):
        seen = {}

        def handler(request):
            seen["auth"] = request.headers.get("Authorization")
            return httpx.Response(200, text=_LONG_TEXT)

        result = self._provider(api_key="jk-123", handler=handler).fetch("https://example.com/", 8000)
        assert result.success
        assert seen["auth"] == "Bearer jk-123"

    def test_429_rate_limited_reason(self):
        result = self._provider(handler=lambda r: httpx.Response(429)).fetch("https://example.com/", 8000)
        assert not result.success and "限流" in result.reason

    def test_http_error_reason(self):
        result = self._provider(handler=lambda r: httpx.Response(500)).fetch("https://example.com/", 8000)
        assert not result.success and "500" in result.reason


class _FakeResult:
    def __init__(self, markdown="", html="", metadata=None):
        self.markdown = markdown
        self.html = html
        self.metadata = metadata


class _FakeCrawler:
    def __init__(self, **kwargs):
        self._entered = False
        self._results = []

    async def __aenter__(self):
        self._entered = True
        return self

    async def close(self):
        self._entered = False

    async def arun(self, url, config=None):
        self._results.append(url)
        return _FakeResult(markdown=_LONG_TEXT)


class _FakeCrawl4ai:
    AsyncWebCrawler = _FakeCrawler

    def CrawlerRunConfig(self, **kwargs):
        return kwargs


class TestCrawl4aiProvider:
    @pytest.fixture
    def fake_crawl4ai(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "crawl4ai", _FakeCrawl4ai())

    def test_fetch_renders_and_marks_provider(self, fake_crawl4ai):
        from competitor_agent.collector.fetch_providers.crawl4ai_fetch import (
            Crawl4aiFetchProvider,
        )

        p = Crawl4aiFetchProvider(headless=True)
        assert p.available()
        result = p.fetch("https://example.com/js-heavy", 8000)
        assert result.success and result.provider == "crawl4ai"
        assert _LONG_TEXT in result.content


class TestBuildFetchRouter:
    def test_fetch_disabled_returns_none(self):
        assert build_fetch_router(CollectorConfig(fetch_enabled=False)) is None

    def test_default_chain_trafilatura_jina(self):
        router = build_fetch_router(CollectorConfig(fetch_enabled=True))
        assert router is not None
        assert [p.source_provider for p in router.providers] == ["trafilatura", "jina"]

    def test_crawl4ai_inserted_when_pool_and_extra(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "crawl4ai", _FakeCrawl4ai())
        cfg = CollectorConfig(fetch_enabled=True, crawler_browser_pool=1)
        router = build_fetch_router(cfg)
        assert [p.source_provider for p in router.providers] == [
            "trafilatura", "crawl4ai", "jina",
        ]

    def test_crawl4ai_not_inserted_when_pool_zero(self):
        router = build_fetch_router(CollectorConfig(fetch_enabled=True, crawler_browser_pool=0))
        assert "crawl4ai" not in [p.source_provider for p in router.providers]

    def test_jina_disabled_removes_level(self):
        router = build_fetch_router(
            CollectorConfig(fetch_enabled=True, jina_reader_enabled=False)
        )
        assert [p.source_provider for p in router.providers] == ["trafilatura"]
