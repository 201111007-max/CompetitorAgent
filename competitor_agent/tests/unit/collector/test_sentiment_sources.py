"""设计文档 67 §2.2 — 舆情采样源单测。

mock httpx：HN Algolia 返回 SentimentSample（含 sample_size/时间窗）、Reddit JSON
解析、平台缺失/失败降级、provider 无 → None。
"""
from __future__ import annotations

import httpx
import pytest

from competitor_agent.collector.sentiment_sources import (
    HackerNewsProvider,
    RedditProvider,
    SentimentError,
    build_sentiment_provider,
)
from competitor_agent.config.loader import CollectorConfig


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _json_client(payload: dict, status: int = 200) -> httpx.Client:
    return _client(lambda req: httpx.Response(status, json=payload))


class TestHackerNewsProvider:
    def test_parses_hits(self):
        client = _json_client(
            {
                "hits": [
                    {
                        "title": "Cursor raises new round",
                        "url": "https://blog.cursor.com/round",
                        "created_at": "2026-08-10T12:00:00Z",
                        "objectID": "123",
                    },
                    {"title": "", "url": "", "objectID": "456"},
                ]
            }
        )
        p = HackerNewsProvider(client=client)
        samples = p.sample("cursor", max_samples=5)
        assert len(samples) == 1
        s = samples[0]
        assert s.platform == "hn"
        assert s.text == "Cursor raises new round"
        assert s.sample_size == 1  # 有效条数回填
        assert "2026-08-10" in s.posted_at

    def test_empty_hits(self):
        p = HackerNewsProvider(client=_json_client({"hits": []}))
        assert p.sample("cursor") == []

    def test_non_2xx_raises(self):
        p = HackerNewsProvider(client=_json_client({"error": "x"}, status=500))
        with pytest.raises(SentimentError):
            p.sample("cursor")

    def test_network_error_raises(self):
        def handler(request):
            raise httpx.ConnectError("boom")

        p = HackerNewsProvider(client=_client(handler))
        with pytest.raises(SentimentError):
            p.sample("cursor")


class TestRedditProvider:
    def test_parses_children(self):
        client = _client(
            lambda req: httpx.Response(
                200,
                json={
                    "data": {
                        "children": [
                            {
                                "data": {
                                    "title": "What do you think of Cursor?",
                                    "permalink": "/r/MachineLearning/comments/abc/",
                                    "created_utc": "1754217600",
                                }
                            }
                        ]
                    }
                },
            )
        )
        p = RedditProvider(subreddits=("MachineLearning",), client=client)
        samples = p.sample("cursor", max_samples=5)
        assert len(samples) == 1
        assert samples[0].platform == "reddit"
        assert samples[0].source_url.startswith("https://www.reddit.com")
        assert samples[0].sample_size == 1

    def test_non_2xx_raises(self):
        p = RedditProvider(subreddits=("MachineLearning",), client=_json_client({}, status=429))
        with pytest.raises(SentimentError):
            p.sample("cursor")


class TestBuildSentimentProvider:
    def test_disabled_by_default(self):
        assert build_sentiment_provider(CollectorConfig(sentiment_provider="hackernews")) is None

    def test_unknown_name_returns_none(self):
        cfg = CollectorConfig(enable_external_sources=True, sentiment_provider="twitter")
        assert build_sentiment_provider(cfg) is None

    def test_enabled_returns_instance(self):
        cfg = CollectorConfig(enable_external_sources=True, sentiment_provider="hackernews")
        assert isinstance(build_sentiment_provider(cfg), HackerNewsProvider)
