"""设计文档 71 §5.3/§6.1 — FetchPolicy 单跑去重 + 上限；FetchCache 分级缓存 + URL 规范化。

覆盖（§9 验收）：同 URL 只抓一次不重计上限；累计超 FETCH_MAX_PER_RUN 返回「已达上限」；
搜索缓存 24h / 正文缓存 7d 命中不重发；TTL 过期失效；canonical_url 去 fragment/大小写。
"""
from __future__ import annotations

import threading
import time

from competitor_agent.collector.fetch import FetchResult
from competitor_agent.collector.fetch_cache import FetchCache
from competitor_agent.collector.fetch_policy import FetchPolicy
from competitor_agent.collector.search import SearchHit


class TestFetchPolicy:
    def test_same_url_dedup_not_recounted(self):
        policy = FetchPolicy(max_per_run=6)
        result = FetchResult(success=True, url="https://a.com", content="正文" * 30)
        kind, note = policy.get("https://a.com")
        assert kind == "ok"
        policy.record("https://a.com", result)
        assert policy.count == 1
        # 第二次调用：去重回读，不重抓、不计上限
        kind, note = policy.get("https://a.com")
        assert kind == "cached"
        assert note is result
        assert policy.count == 1

    def test_limit_hit_after_max(self):
        policy = FetchPolicy(max_per_run=2)
        r = FetchResult(success=True, url="", content="x" * 100)
        for i in range(2):
            url = f"https://a{i}.com"
            assert policy.get(url)[0] == "ok"
            policy.record(url, r)
        kind, note = policy.get("https://a2.com")
        assert kind == "limit"
        assert "已达上限" in note and "2 次" in note

    def test_limit_respects_dedup_first(self):
        policy = FetchPolicy(max_per_run=1)
        r = FetchResult(success=True, url="https://a.com", content="y" * 100)
        policy.record("https://a.com", r)
        # 已抓过的 URL 命中去重，即使已满也返回 cached（不触发 limit）
        kind, _ = policy.get("https://a.com")
        assert kind == "cached"

    def test_concurrent_same_url_fetched_once(self):
        """review 修复（P1）：FetchPolicy 线程安全——并发同 URL 只抓一次、不超上限。"""
        policy = FetchPolicy(max_per_run=6)
        r = FetchResult(success=True, url="https://a.com", content="x" * 100)
        barrier = threading.Barrier(8)
        results: list[str] = []
        lock = threading.Lock()

        def worker():
            barrier.wait()
            kind, _ = policy.get("https://a.com")
            if kind == "ok":
                policy.record("https://a.com", r)
                with lock:
                    results.append("fetched")

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results.count("fetched") == 1  # 只抓一次
        assert policy.count == 1


class TestFetchCache:
    def test_canonical_url(self):
        assert FetchCache.canonical_url("https://Example.com/a#frag") == "https://example.com/a"
        assert FetchCache.canonical_url("http://example.com:80/x") == "http://example.com/x"
        assert FetchCache.canonical_url("https://a.com/b?q=1#x") == "https://a.com/b?q=1"

    def test_canonical_url_malformed_port_no_crash(self):
        """review 修复（P1）：畸形端口（:abc / :99999）不抛异常（web_extract「不抛」契约）。"""
        assert FetchCache.canonical_url("https://example.com:abc/x") == "https://example.com/x"
        assert "http://" in FetchCache.canonical_url("http://example.com:99999/x")

    def test_search_roundtrip_and_ttl(self, tmp_path):
        cache = FetchCache(data_dir=tmp_path, search_ttl_hours=24, fetch_ttl_days=7)
        hits = [SearchHit("A", "https://a.com", "s", source_engine="duckduckgo", fetched_at=1.0)]
        assert cache.get_search("q", 5, "duckduckgo") is None
        cache.set_search("q", 5, "duckduckgo", hits)
        back = cache.get_search("q", 5, "duckduckgo")
        assert back is not None
        assert back[0].url == "https://a.com"
        assert back[0].source_engine == "duckduckgo"
        # 不同 max_results / engine 不命中
        assert cache.get_search("q", 6, "duckduckgo") is None

    def test_search_ttl_expiry(self, tmp_path, monkeypatch):
        cache = FetchCache(data_dir=tmp_path, search_ttl_hours=0, fetch_ttl_days=7)
        cache.set_search("q", 5, "duckduckgo", [SearchHit("A", "https://a.com", "s")])
        assert cache.get_search("q", 5, "duckduckgo") is None  # TTL 0 立即过期

    def test_fetch_roundtrip_and_canonical_dedup(self, tmp_path):
        cache = FetchCache(data_dir=tmp_path, search_ttl_hours=24, fetch_ttl_days=7)
        result = FetchResult(
            success=True, url="https://A.com/x#frag", content="正文" * 20,
            provider="trafilatura", fetched_at=time.time(),
        )
        cache.set_fetch(result)
        back = cache.get_fetch("https://a.com/x")  # 大小写/去 fragment 后命中
        assert back is not None and back.provider == "trafilatura"
        assert back.content == result.content

    def test_fetch_ttl_expiry(self, tmp_path):
        cache = FetchCache(data_dir=tmp_path, search_ttl_hours=24, fetch_ttl_days=0)
        cache.set_fetch(
            FetchResult(success=True, url="https://a.com", content="x" * 100, provider="jina")
        )
        assert cache.get_fetch("https://a.com") is None  # TTL 0 立即过期

    def test_failed_fetch_not_cached(self, tmp_path):
        cache = FetchCache(data_dir=tmp_path)
        cache.set_fetch(FetchResult(success=False, url="https://a.com", reason="HTTP 403"))
        assert cache.get_fetch("https://a.com") is None
