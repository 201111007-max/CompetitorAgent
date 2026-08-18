"""跨竞品同源去重测试（设计文档 49 §3.4）

进程内 URL → Observation 缓存：同源 URL 二次抓取直接复用（省网络请求、跨竞品引用同版本数据）；
URL 不同但 content_hash 一致 → 复用；内容不同绝不复用；有界 FIFO 淘汰。
"""
from __future__ import annotations

from competitor_agent.core.source_dedup import SourceDedup, _normalize_url
from competitor_agent.domain_types.observation import Observation, SourceEvidence


def _obs(url: str, content_hash: str, gap_field: str = "pricing") -> Observation:
    return Observation(
        gap_field=gap_field,
        source="web_extractor",
        raw_text=f"text@{url}",
        evidence=SourceEvidence(
            source_name="web_extractor", url=url, content_hash=content_hash, trust_level=0.9
        ),
    )


class TestNormalizeUrl:
    def test_strips_fragment(self):
        assert _normalize_url("https://cursor.com/pricing#tiers") == "https://cursor.com/pricing"

    def test_lowercases_scheme_host(self):
        assert _normalize_url("HTTPS://Cursor.com/Pricing") == "https://cursor.com/Pricing"

    def test_strips_trailing_slash(self):
        assert _normalize_url("https://cursor.com/pricing/") == "https://cursor.com/pricing"

    def test_root_slash_preserved(self):
        assert _normalize_url("https://cursor.com/") == "https://cursor.com"

    def test_strips_whitespace(self):
        assert _normalize_url("  https://cursor.com/pricing  ") == "https://cursor.com/pricing"


class TestSourceDedup:
    def test_same_url_reuses_cached(self):
        dedup = SourceDedup()
        calls = []
        a = _obs("https://cursor.com/pricing", "h1")

        def fetch():
            calls.append(1)
            return a

        first = dedup.get_or_fetch("https://cursor.com/pricing", fetch)
        second = dedup.get_or_fetch("https://cursor.com/pricing", fetch)
        assert first is second
        assert len(calls) == 1  # 第二次未再抓取
        assert dedup.hit_count == 1
        assert dedup.total_lookups == 2

    def test_url_variants_share_cache(self):
        dedup = SourceDedup()
        calls = []
        a = _obs("https://cursor.com/pricing", "h1")

        def fetch():
            calls.append(1)
            return a

        dedup.get_or_fetch("https://cursor.com/pricing", fetch)
        dedup.get_or_fetch("HTTPS://cursor.com/pricing/#top", fetch)
        assert len(calls) == 1

    def test_content_hash_reuse_across_urls(self):
        dedup = SourceDedup()
        calls = []
        a = _obs("https://a.com/page", "same-hash")
        b = _obs("https://b.com/mirror", "same-hash")

        def make(cand):
            def fetch():
                calls.append(cand)
                return cand

            return fetch

        first = dedup.get_or_fetch("https://a.com/page", make(a))
        second = dedup.get_or_fetch("https://b.com/mirror", make(b))
        assert second is first  # 不同 URL 同内容 → 复用同一缓存对象
        assert len(calls) == 2  # 第二次需抓取才能比对内容哈希
        # 两个 URL 键指向同一 Observation 对象（跨竞品同内容一致）
        assert dedup._by_url["https://b.com/mirror"] is first

    def test_different_content_not_reused(self):
        dedup = SourceDedup()
        a = _obs("https://a.com/page", "hash-a")
        b = _obs("https://b.com/page", "hash-b")
        first = dedup.get_or_fetch("https://a.com/page", lambda: a)
        second = dedup.get_or_fetch("https://b.com/page", lambda: b)
        assert second is not first
        assert dedup.cache_size == 2
        assert dedup.hit_count == 0

    def test_fifo_eviction(self):
        dedup = SourceDedup(max_size=2)
        a = _obs("https://a.com/1", "h1")
        b = _obs("https://b.com/2", "h2")
        c = _obs("https://c.com/3", "h3")
        dedup.get_or_fetch("https://a.com/1", lambda: a)
        dedup.get_or_fetch("https://b.com/2", lambda: b)
        dedup.get_or_fetch("https://c.com/3", lambda: c)
        assert dedup.cache_size == 2
        assert "https://a.com/1" not in dedup._by_url  # 最旧被淘汰

    def test_clear_resets(self):
        dedup = SourceDedup()
        a = _obs("https://a.com/1", "h1")
        dedup.get_or_fetch("https://a.com/1", lambda: a)
        dedup.clear()
        assert dedup.cache_size == 0
        assert dedup.hit_count == 0
        assert dedup.total_lookups == 0
