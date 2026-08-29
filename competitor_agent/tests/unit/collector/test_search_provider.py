"""设计文档 66 §3.1 — 真实 Tavily 搜索接入单测。

覆盖：
① TavilySearchProvider（mock httpx：200 正常映射 title/url/snippet、空 results、
   非 2xx 抛 SearchError、网络/超时抛、Bearer 鉴权头）；
② build_search_provider（缺 Key / 空名 / 未知名 → None，tavily+Key → 实例）；
③ web_search_candidates（hits → LLM 归纳候选；空 hits → [];LLM 畸形 → [] 不抛；
   provider 失败 → [] 不编造）。
"""
from __future__ import annotations

import httpx
import pytest

from competitor_agent.collector.search import (
    SearchError,
    SearchHit,
    TavilySearchProvider,
    build_search_provider,
    web_search_candidates,
)
from competitor_agent.config.loader import CollectorConfig


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _json_client(payload: dict, status: int = 200) -> httpx.Client:
    def handler(request):
        return httpx.Response(status, json=payload)

    return _client(handler)


class TestTavilySearchProvider:
    def test_200_maps_hits(self):
        client = _json_client(
            {
                "results": [
                    {"title": "Cursor", "url": "https://cursor.com", "content": "AI editor"},
                    {"title": "", "url": "", "content": "noise"},
                ]
            }
        )
        p = TavilySearchProvider("tvly-x", client=client)
        hits = p.search("cursor", max_results=5)
        assert hits == [
            SearchHit(title="Cursor", url="https://cursor.com", snippet="AI editor")
        ]
        # 无 url 的条目被剔除
        assert len(hits) == 1

    def test_200_empty_results(self):
        client = _json_client({"results": []})
        p = TavilySearchProvider("tvly-x", client=client)
        assert p.search("nothing") == []

    def test_non_2xx_raises(self):
        client = _json_client({"error": "unauthorized"}, status=401)
        p = TavilySearchProvider("tvly-x", client=client)
        with pytest.raises(SearchError):
            p.search("cursor")

    def test_network_error_raises(self):
        def handler(request):
            raise httpx.ConnectError("boom")

        p = TavilySearchProvider("tvly-x", client=_client(handler))
        with pytest.raises(SearchError):
            p.search("cursor")

    def test_timeout_raises(self):
        def handler(request):
            raise httpx.ReadTimeout("slow")

        p = TavilySearchProvider("tvly-x", client=_client(handler))
        with pytest.raises(SearchError):
            p.search("cursor")

    def test_sends_bearer_auth_and_payload(self):
        seen: dict[str, object] = {}

        def handler(request):
            seen["auth"] = request.headers.get("Authorization")
            seen["json"] = request.content
            return httpx.Response(200, json={"results": []})

        p = TavilySearchProvider("tvly-secret", client=_client(handler))
        p.search("coding agent", max_results=3)
        assert seen["auth"] == "Bearer tvly-secret"


class TestBuildSearchProvider:
    def test_missing_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        assert build_search_provider(CollectorConfig(search_provider="tavily")) is None

    def test_empty_provider_name_returns_none(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
        assert build_search_provider(CollectorConfig(search_provider="")) is None

    def test_unknown_name_returns_none(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
        assert build_search_provider(CollectorConfig(search_provider="serpapi")) is None

    def test_tavily_with_key_returns_instance(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
        p = build_search_provider(CollectorConfig(search_provider="tavily"))
        assert isinstance(p, TavilySearchProvider)


class _FakeProvider:
    def __init__(self, hits):
        self._hits = hits

    def search(self, query, max_results=8):
        return self._hits


class _FakeLLM:
    def __init__(self, text):
        self._text = text
        self.messages = None

    def complete(self, messages, **kwargs):
        self.messages = messages
        return self._text


class TestWebSearchCandidates:
    def test_returns_candidates(self):
        provider = _FakeProvider([SearchHit("Cursor", "https://cursor.com", "s")])
        llm = _FakeLLM('[{"name": "cursor", "home": "https://cursor.com"}]')
        out = web_search_candidates("coding agents", provider, llm, max_results=5)
        assert out == [{"name": "cursor", "home": "https://cursor.com"}]
        # LLM 收到 hits 归纳提示（system + user）
        assert llm.messages[0]["role"] == "system"
        assert "https://cursor.com" in llm.messages[1]["content"]

    def test_empty_hits_returns_empty(self):
        provider = _FakeProvider([])
        llm = _FakeLLM('[{"name": "x"}]')
        assert web_search_candidates("x", provider, llm) == []

    def test_provider_none_returns_empty(self):
        assert web_search_candidates("x", None, _FakeLLM("[]")) == []

    def test_llm_none_returns_empty(self):
        provider = _FakeProvider([SearchHit("Cursor", "https://cursor.com", "s")])
        assert web_search_candidates("x", provider, None) == []

    def test_llm_malformed_returns_empty_no_throw(self):
        provider = _FakeProvider([SearchHit("Cursor", "https://cursor.com", "s")])
        llm = _FakeLLM("不是 JSON")
        assert web_search_candidates("x", provider, llm) == []

    def test_provider_error_returns_empty(self):
        class Boom:
            def search(self, query, max_results=8):
                raise SearchError("boom")

        assert web_search_candidates("x", Boom(), _FakeLLM("[]")) == []
