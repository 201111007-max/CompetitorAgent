"""设计文档 74 §3.5 — 外部通道熔断 + stale-while-revalidate 单测。

- CircuitBreaker 三态（closed/open/half-open）+ 指数退避（时钟注入，禁真等待）；
- SearchRouter/FetchRouter 逐源熔断：连续失败 N 次 → 冷却内跳过切备用；全源熔断显式不可用；
- SWR：抓取失败 → 过期旧缓存兜底 + as_of 标注；无缓存/开关关闭 → 原失败文案；
- 黄金回归：threshold=0（默认直接构造）行为逐字节不变；成功路径零改动（全 mock 不联网）。
"""
from __future__ import annotations

import json

import pytest

from competitor_agent.collector.fetch import FetchResult, FetchRouter
from competitor_agent.collector.fetch_cache import FetchCache
from competitor_agent.collector.resilience import CircuitBreaker
from competitor_agent.collector.search import SearchError, SearchHit, SearchRouter
from competitor_agent.mcp_server.tools import web_tools

_LONG = "正文内容 " * 200


class _FakeSearchProvider:
    """可控搜索 provider：脚本逐次抛错/返回；脚本耗尽后重复最后一项。"""

    def __init__(self, engine: str, script: list) -> None:
        self.source_engine = engine
        self._script = list(script)
        self.calls = 0

    def _next(self):
        if len(self._script) > 1:
            return self._script.pop(0)
        return self._script[0]

    def search(self, query: str, max_results: int = 8) -> list[SearchHit]:
        self.calls += 1
        action = self._next()
        if isinstance(action, Exception):
            raise action
        return action


def _hits(engine: str) -> list[SearchHit]:
    return [SearchHit(title="t", url="https://example.com", snippet="s", source_engine=engine)]


class _FakeFetchProvider:
    """可控抓取 provider（鸭子类型：FetchRouter 只用 available/fetch）。"""

    def __init__(self, level: str, script: list) -> None:
        self.source_provider = level
        self._script = list(script)
        self.calls = 0

    def available(self) -> bool:
        return True

    def _next(self):
        if len(self._script) > 1:
            return self._script.pop(0)
        return self._script[0]

    def fetch(self, url: str, max_chars: int) -> FetchResult:
        self.calls += 1
        action = self._next()
        if isinstance(action, Exception):
            raise action
        return action


def _fail(reason: str) -> FetchResult:
    return FetchResult(success=False, url="u", reason=reason)


def _ok(level: str) -> FetchResult:
    return FetchResult(success=True, url="u", content=_LONG, provider=level)


# ── CircuitBreaker 三态 ──────────────────────────────────────────


class TestCircuitBreaker:
    def test_below_threshold_stays_closed(self) -> None:
        clock = {"t": 0.0}
        breaker = CircuitBreaker(
            "s", threshold=3, cooldown_seconds=60.0, now_fn=lambda: clock["t"]
        )
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == "closed"
        assert breaker.allow() is True

    def test_threshold_opens_and_blocks(self) -> None:
        clock = {"t": 0.0}
        breaker = CircuitBreaker(
            "s", threshold=2, cooldown_seconds=60.0, now_fn=lambda: clock["t"]
        )
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == "open"
        assert breaker.allow() is False

    def test_half_open_probe_success_closes(self) -> None:
        clock = {"t": 0.0}
        breaker = CircuitBreaker(
            "s", threshold=1, cooldown_seconds=60.0, now_fn=lambda: clock["t"]
        )
        breaker.record_failure()
        assert breaker.allow() is False
        clock["t"] = 61.0
        assert breaker.allow() is True  # 冷却到期 → half-open 放行探测
        breaker.record_success()
        assert breaker.state == "closed"
        assert breaker.allow() is True

    def test_half_open_failure_reopens_with_backoff(self) -> None:
        clock = {"t": 0.0}
        breaker = CircuitBreaker(
            "s", threshold=1, cooldown_seconds=60.0, now_fn=lambda: clock["t"]
        )
        breaker.record_failure()  # open（冷却 60s）
        clock["t"] = 61.0
        assert breaker.allow() is True  # half-open
        breaker.record_failure()  # 探测失败 → 重新 open，冷却翻倍 120s
        assert breaker.state == "open"
        clock["t"] = 61.0 + 60.0
        assert breaker.allow() is False  # 120s 未到
        clock["t"] = 61.0 + 121.0
        assert breaker.allow() is True

    def test_backoff_capped_at_8x(self) -> None:
        clock = {"t": 0.0}
        breaker = CircuitBreaker(
            "s", threshold=1, cooldown_seconds=60.0, now_fn=lambda: clock["t"]
        )
        breaker.record_failure()  # open（60s）
        for expected in (120.0, 240.0, 480.0, 480.0):  # 翻倍 → 8× 封顶
            clock["t"] += 100000.0
            assert breaker.allow() is True  # half_open
            breaker.record_failure()
            assert breaker._cooldown == expected


# ── SearchRouter 熔断 ────────────────────────────────────────────


class TestSearchRouterBreaker:
    def test_consecutive_failures_skip_source(self) -> None:
        a = _FakeSearchProvider("ddg", [SearchError("boom"), SearchError("boom")])
        b = _FakeSearchProvider("tavily", [_hits("tavily")])
        router = SearchRouter([a, b], breaker_threshold=2, breaker_cooldown_seconds=60.0)
        assert router.search("q")[0].source_engine == "tavily"  # A 失败 1 → B
        assert router.search("q")[0].source_engine == "tavily"  # A 失败 2 → 熔断
        assert a.calls == 2
        assert router.search("q")[0].source_engine == "tavily"  # A 被跳过，B 服务
        assert a.calls == 2

    def test_cooldown_probe_success_closes(self) -> None:
        clock = {"t": 1000.0}
        a = _FakeSearchProvider("ddg", [SearchError("boom"), _hits("ddg")])
        b = _FakeSearchProvider("tavily", [_hits("tavily")])
        router = SearchRouter([a, b], breaker_threshold=1, breaker_cooldown_seconds=10.0)
        # 统一假时钟（必须在首次失败记录前注入，opened_at 同源）
        breaker = router._breaker_for("ddg")
        breaker._now_fn = lambda: clock["t"]
        assert router.search("q")[0].source_engine == "tavily"  # A 失败 → 熔断
        assert a.calls == 1
        assert router.search("q")[0].source_engine == "tavily"  # 冷却内跳过
        assert a.calls == 1
        clock["t"] = 1011.0  # 冷却 10s 到期 → 半开探测
        assert router.search("q")[0].source_engine == "ddg"
        assert a.calls == 2
        assert breaker.state == "closed"

    def test_all_sources_open_raises(self) -> None:
        a = _FakeSearchProvider("ddg", [SearchError("e")] * 3)
        b = _FakeSearchProvider("tavily", [SearchError("e")] * 3)
        router = SearchRouter([a, b], breaker_threshold=3, breaker_cooldown_seconds=60.0)
        for _ in range(3):
            with pytest.raises(SearchError):
                router.search("q")
        assert a.calls == 3 and b.calls == 3
        # 第 4 次：全源熔断 → 显式不可用（不伪装「未搜索到」）
        with pytest.raises(SearchError, match="熔断"):
            router.search("q")
        assert a.calls == 3 and b.calls == 3

    def test_disabled_by_default(self) -> None:
        a = _FakeSearchProvider("ddg", [SearchError("e")])
        b = _FakeSearchProvider("tavily", [_hits("tavily")])
        router = SearchRouter([a, b])  # threshold 缺省 0 = 关闭
        for _ in range(5):
            assert router.search("q")[0].source_engine == "tavily"
        assert a.calls == 5  # 无熔断：每次都先试主力


# ── FetchRouter 熔断 ─────────────────────────────────────────────


class TestFetchRouterBreaker:
    def test_consecutive_failures_skip_level(self) -> None:
        a = _FakeFetchProvider("trafilatura", [_fail("403"), _fail("403")])
        b = _FakeFetchProvider("jina", [_ok("jina")])
        router = FetchRouter([a, b], breaker_threshold=2, breaker_cooldown_seconds=60.0)
        assert router.fetch("https://example.com/", 8000).provider == "jina"
        assert router.fetch("https://example.com/", 8000).provider == "jina"
        assert a.calls == 2
        assert router.fetch("https://example.com/", 8000).provider == "jina"
        assert a.calls == 2  # 熔断中被跳过

    def test_all_levels_open_explicit_failure(self) -> None:
        a = _FakeFetchProvider("trafilatura", [_fail("403")] * 3)
        b = _FakeFetchProvider("jina", [_fail("403")] * 3)
        router = FetchRouter([a, b], breaker_threshold=3, breaker_cooldown_seconds=60.0)
        for _ in range(3):
            result = router.fetch("https://example.com/", 8000)
            assert result.success is False
        result = router.fetch("https://example.com/", 8000)
        assert result.success is False
        assert "熔断" in result.reason
        assert a.calls == 3 and b.calls == 3

    def test_disabled_by_default(self) -> None:
        a = _FakeFetchProvider("trafilatura", [_fail("403")])
        b = _FakeFetchProvider("jina", [_ok("jina")])
        router = FetchRouter([a, b])  # 缺省关闭
        for _ in range(5):
            assert router.fetch("https://example.com/", 8000).provider == "jina"
        assert a.calls == 5


# ── SWR：抓取失败回旧缓存 ────────────────────────────────────────


def _seed_stale(cache: FetchCache, url: str) -> None:
    """预置一条过期缓存（fetched_at=0 → 必过期）：get_fetch 未命中、get_fetch_stale 命中。"""
    pre = FetchResult(
        success=True, url=url, content="旧缓存内容", provider="jina", fetched_at=123.0
    )
    cache.set_fetch(pre)
    path = cache._fetch_dir / f"{cache._key(cache.canonical_url(url))}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["fetched_at"] = 0.0
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class TestStaleWhileRevalidate:
    def test_failure_serves_stale_with_as_of(self, tmp_path) -> None:
        url = "https://example.com/anti-crawl"
        cache = FetchCache(data_dir=tmp_path / "cache", fetch_ttl_days=0)
        _seed_stale(cache, url)
        assert cache.get_fetch(url) is None  # TTL 过期，正常路径未命中
        failing = FetchRouter([_FakeFetchProvider("trafilatura", [_fail("反爬 403")])])
        out = web_tools._web_extract_impl(url, fetch_router=failing, fetch_cache=cache)
        assert "旧缓存内容" in out
        assert "stale 缓存 as_of 未知" in out  # fetched_at=0 → 未记录（项目时间戳约定）
        assert "待核验" in out

    def test_failure_without_cache_keeps_error_text(self, tmp_path) -> None:
        cache = FetchCache(data_dir=tmp_path / "cache")
        failing = FetchRouter([_FakeFetchProvider("trafilatura", [_fail("HTTP 403")])])
        out = web_tools._web_extract_impl(
            "https://example.com/x", fetch_router=failing, fetch_cache=cache
        )
        assert out.startswith("抓取失败:") and "HTTP 403" in out

    def test_switch_off_disables_swr(self, tmp_path, monkeypatch) -> None:
        from competitor_agent.config.loader import AppConfig

        url = "https://example.com/x"
        cache = FetchCache(data_dir=tmp_path / "cache", fetch_ttl_days=0)
        _seed_stale(cache, url)
        cfg = AppConfig()
        cfg.collector.stale_cache_on_failure = False
        monkeypatch.setattr(
            "competitor_agent.mcp_server.tools.web_tools.load_config", lambda: cfg
        )
        failing = FetchRouter([_FakeFetchProvider("trafilatura", [_fail("403")])])
        out = web_tools._web_extract_impl(url, fetch_router=failing, fetch_cache=cache)
        assert out.startswith("抓取失败:")

    def test_get_fetch_stale_ignores_ttl(self, tmp_path) -> None:
        cache = FetchCache(data_dir=tmp_path / "cache", fetch_ttl_days=0)
        _seed_stale(cache, "https://example.com/a")
        assert cache.get_fetch("https://example.com/a") is None
        stale = cache.get_fetch_stale("https://example.com/a")
        assert stale is not None and stale.success and stale.stale is True
        assert stale.content == "旧缓存内容"
