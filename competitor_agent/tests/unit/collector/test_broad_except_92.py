"""设计文档 92 下批 — 采集层无日志广捕补 source+原因（doc 92 收尾建议）。

- FetchCache 缓存条目损坏 → 返回 None（未命中语义不变）+ WARNING 带定位信息；
- WebExtractor lxml 解析失败回退 html.parser → WARNING 带 url（monkeypatch 确定性触发）。

行为语义零变化（黄金回归）：只补可观测性，不改变任何返回值/控制流。
"""
from __future__ import annotations

import json
import logging

import bs4

from competitor_agent.collector.fetch_cache import FetchCache
from competitor_agent.collector.web_extractor import WebExtractor


class TestCacheCorruptionLogged:
    def test_search_cache_corruption_warns(self, tmp_path, caplog) -> None:
        import time

        cache = FetchCache(data_dir=tmp_path / "cache")
        cache.set_search("q", 5, "duckduckgo", [])
        target = next(cache._search_dir.glob("*.json"))
        # 新鲜时间戳（过 _read 的 TTL 检查）+ 结构坏（hits 为 dict）→ 落 get_search 解析守卫
        target.write_text(
            json.dumps({"hits": {"bad": 1}, "fetched_at": time.time()}), encoding="utf-8"
        )
        with caplog.at_level(logging.WARNING, logger="competitor_agent.collector.fetch_cache"):
            assert cache.get_search("q", 5, "duckduckgo") is None
        assert "搜索缓存解析失败" in caplog.text
        assert "duckduckgo" in caplog.text

    def test_fetch_cache_corruption_warns(self, tmp_path, caplog) -> None:
        cache = FetchCache(data_dir=tmp_path / "cache")
        # data 非 dict（JSON 数组）→ _fetch_from 内 data.get 炸 → 解析守卫
        with caplog.at_level(logging.WARNING, logger="competitor_agent.collector.fetch_cache"):
            assert cache._fetch_from(["not-a-dict"], "https://example.com/a") is None
        assert "正文缓存解析失败" in caplog.text
        assert "example.com" in caplog.text


class TestWebExtractorFallbackLogged:
    def test_lxml_fallback_warns_with_url(self, caplog, monkeypatch) -> None:
        """lxml 抛错 → 回退 html.parser + WARNING 带 url（回退分支确定性触发）。"""
        real_beautifulsoup = bs4.BeautifulSoup

        def fake_beautifulsoup(markup, parser):
            if parser == "lxml":
                raise ValueError("lxml boom（测试注入）")
            return real_beautifulsoup(markup, parser)

        monkeypatch.setattr(bs4, "BeautifulSoup", fake_beautifulsoup)
        html = "<html><body><p>页面正文</p></body></html>"
        extractor = WebExtractor()
        with caplog.at_level(logging.WARNING, logger="competitor_agent.collector.web_extractor"):
            text = extractor._clean(html, url="https://example.com/bad")
        assert "lxml 解析失败" in caplog.text
        assert "example.com/bad" in caplog.text
        assert "页面正文" in text  # 回退后语义不变
