"""设计文档 71 §3.2/§4.3/§5.3 — web_search/web_extract 工具层（str→str 契约）。

覆盖（§9 验收）：web_search 文本块带 `·via:{engine}·{time}` 标注 / 空结果 / 失败不编造 /
未启用提示；web_extract 链成功 via + 单跑去重 + 上限提示 + 磁盘缓存命中 + 失败 reason。
"""
from __future__ import annotations

import pytest

from competitor_agent.collector.fetch import FetchResult, FetchRouter
from competitor_agent.collector.fetch_cache import FetchCache
from competitor_agent.collector.fetch_policy import FetchPolicy
from competitor_agent.collector.search import SearchError, SearchHit, SearchRouter
from competitor_agent.config.loader import AppConfig
from competitor_agent.mcp_server.tools import web_tools

_LONG = "这是足够长的正文内容用于通过空壳检测。" * 20


class _FakeProvider:
    def __init__(self, hits, error=None, engine="duckduckgo"):
        self._hits = hits
        self._error = error
        self.source_engine = engine

    def search(self, query, max_results=8):
        if self._error is not None:
            raise self._error
        return list(self._hits)


class TestWebSearch:
    def test_hits_formatted_with_via(self, monkeypatch):
        hits = [
            SearchHit("Cursor", "https://cursor.com", "AI editor",
                      source_engine="duckduckgo", fetched_at=1700000000.0)
        ]
        monkeypatch.setattr(web_tools, "build_search_router", lambda cfg: _FakeProvider(hits))
        out = web_tools.web_search("cursor")
        assert "Cursor\nhttps://cursor.com\nAI editor·via:duckduckgo·1700000000" in out

    def test_tavily_fallback_via_marked(self, monkeypatch):
        # 主力 DDG 抛错 → 降级 Tavily 命中 → via: tavily（由 router 标注）
        router = SearchRouter(
            [
                _FakeProvider([], error=SearchError("限流", kind="rate_limited"), engine="duckduckgo"),
                _FakeProvider([SearchHit("B", "https://b.com", "s")], engine="tavily"),
            ]
        )
        monkeypatch.setattr(web_tools, "build_search_router", lambda cfg: router)
        out = web_tools.web_search("q")
        assert "via:tavily" in out

    def test_empty_result_message(self, monkeypatch):
        monkeypatch.setattr(web_tools, "build_search_router", lambda cfg: _FakeProvider([]))
        out = web_tools.web_search("nothing")
        assert "未搜索到" in out

    def test_failure_returns_readable_not_raise(self, monkeypatch):
        monkeypatch.setattr(
            web_tools, "build_search_router",
            lambda cfg: _FakeProvider([], error=SearchError("boom", kind="network")),
        )
        out = web_tools.web_search("q")
        assert "搜索暂不可用" in out and "boom" in out

    def test_disabled_main_switch_readable(self, monkeypatch):
        cfg = AppConfig()
        cfg.collector.enable_external_sources = False
        monkeypatch.setattr(web_tools, "load_config", lambda: cfg)
        out = web_tools.web_search("q")
        assert "搜索功能未启用" in out


class _FakeFetchProvider:
    def __init__(self, result, level="trafilatura"):
        self._result = result
        self.source_provider = level

    def available(self):
        return True

    def fetch(self, url, max_chars):
        return self._result


class TestWebExtract:
    @pytest.fixture(autouse=True)
    def _resolve_public(self, monkeypatch):
        # 无网络测试环境：URL 守卫 DNS 解析打桩为公网 IP
        import socket

        def fake(host, *_a, **_k):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

        monkeypatch.setattr(socket, "getaddrinfo", fake)

    def _impl(self, url="https://example.com/", **kw):
        return web_tools._web_extract_impl(url, **kw)

    def test_chain_success_via(self, tmp_path):
        router = FetchRouter(
            [_FakeFetchProvider(FetchResult(success=True, url="u", content=_LONG, provider="trafilatura"))]
        )
        out = self._impl(fetch_router=router, fetch_cache=FetchCache(data_dir=tmp_path / "cache"))
        assert out.startswith("via: trafilatura\n")

    def test_policy_dedup_reuses_content(self, tmp_path):
        router = FetchRouter(
            [_FakeFetchProvider(FetchResult(success=True, url="u", content=_LONG, provider="trafilatura"))]
        )
        policy = FetchPolicy(max_per_run=6)
        cache = FetchCache(data_dir=tmp_path / "cache")
        out1 = self._impl(fetch_router=router, fetch_policy=policy, fetch_cache=cache)
        out2 = self._impl(fetch_router=router, fetch_policy=policy, fetch_cache=cache)
        assert out1 == out2
        assert policy.count == 1  # 同 URL 只抓一次、不重计

    def test_policy_limit_message(self, tmp_path):
        policy = FetchPolicy(max_per_run=1)
        # 先占满 1 次（去重 URL），再访问新 URL → limit
        router = FetchRouter(
            [_FakeFetchProvider(FetchResult(success=True, url="u", content=_LONG, provider="trafilatura"))]
        )
        cache = FetchCache(data_dir=tmp_path / "cache")
        out = self._impl("https://a.com/", fetch_router=router, fetch_policy=policy, fetch_cache=cache)
        assert "via:" in out
        out2 = self._impl("https://b.com/", fetch_router=router, fetch_policy=policy, fetch_cache=cache)
        assert "已达上限" in out2

    def test_disk_cache_hit_no_refetch(self, tmp_path):
        cache = FetchCache(data_dir=tmp_path / "cache")
        router = FetchRouter(
            [_FakeFetchProvider(FetchResult(success=True, url="u", content=_LONG, provider="jina"), level="jina")]
        )
        out1 = self._impl(fetch_router=router, fetch_cache=cache)
        assert "via: jina" in out1
        # 第二次：换一个会失败的 router，也应命中磁盘缓存返回旧内容
        failing = FetchRouter(
            [_FakeFetchProvider(FetchResult(success=False, url="u", reason="网络错误"), level="trafilatura")]
        )
        out2 = self._impl(fetch_router=failing, fetch_cache=cache)
        assert "via: jina" in out2

    def test_all_failed_reason(self, tmp_path):
        router = FetchRouter(
            [_FakeFetchProvider(FetchResult(success=False, url="u", reason="HTTP 403"), level="trafilatura")]
        )
        out = self._impl(fetch_router=router, fetch_cache=FetchCache(data_dir=tmp_path / "cache"))
        assert out.startswith("抓取失败:") and "HTTP 403" in out

    def test_cache_hit_before_limit(self, tmp_path):
        """review 修复（P2）：磁盘缓存命中先于单跑上限——超限时命中缓存仍返回内容。"""
        cache = FetchCache(data_dir=tmp_path / "cache")
        policy = FetchPolicy(max_per_run=1)
        router = FetchRouter(
            [_FakeFetchProvider(FetchResult(success=True, url="u", content=_LONG, provider="trafilatura"))]
        )
        # 先用 https://a.com/ 占满上限，再把 https://c.com/ 预置进磁盘缓存
        self._impl("https://a.com/", fetch_router=router, fetch_policy=policy, fetch_cache=cache)
        pre = FetchResult(success=True, url="https://c.com/", content=_LONG, provider="jina")
        cache.set_fetch(pre)
        out = self._impl("https://c.com/", fetch_router=router, fetch_policy=policy, fetch_cache=cache)
        assert "via: jina" in out  # 磁盘命中，不被「已达上限」挡住
        assert "已达上限" not in out
