"""第 3 级抓取 provider — Jina Reader 云端兜底（设计文档 71 §3.4）。

GET ``https://r.jina.ai/{url}`` 云端转译（免 Key 限 20 次/分；有 ``JINA_API_KEY``
带 ``Authorization: Bearer`` 提额）。无额外依赖（httpx）。URL 守卫：请求 host 是
r.jina.ai（公网），目标 url 在 path——入口已 guard，此处对目标 url 兜底再校验一次。
"""
from __future__ import annotations

import logging
import time

import httpx

from competitor_agent.collector.fetch import FetchProvider, FetchResult
from competitor_agent.core.url_guard import URLError

logger = logging.getLogger("competitor_agent.collector.fetch.jina")

_JINA_READER_URL = "https://r.jina.ai/"
_JINA_KEY_ENV = "JINA_API_KEY"
_DEFAULT_UA = "competitor-agent/0.1"


class JinaFetchProvider(FetchProvider):
    """Jina Reader 云端兜底（秒级、可选 Key 提额；429 计限流降级）。"""

    source_provider = "jina"

    def __init__(
        self,
        api_key: str = "",
        timeout: float = 30.0,
        user_agent: str = _DEFAULT_UA,
        max_content_chars: int = 8000,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._timeout = timeout
        self._user_agent = user_agent
        self._max_content_chars = max_content_chars
        self._client = client

    def fetch(self, url: str, max_chars: int) -> FetchResult:
        try:
            from competitor_agent.core.url_guard import guard_http_url

            guard_http_url(url)  # 目标 url 兜底守卫（对 jina 的 path 参数也校验）
        except URLError as exc:
            return FetchResult(success=False, url=url, reason=f"URL 被安全守卫拦截: {exc}")
        headers = {"User-Agent": self._user_agent, "X-Return-Format": "markdown"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        target = _JINA_READER_URL + url
        try:
            resp = self._get_client().get(target, headers=headers, timeout=self._timeout)
        except httpx.HTTPError as exc:
            return FetchResult(success=False, url=url, reason=f"Jina 请求失败: {exc}")
        if resp.status_code == 429:
            logger.warning("jina 限流 429（免费档 20 次/分，配 %s 提额）", _JINA_KEY_ENV)
            return FetchResult(success=False, url=url, reason="Jina 限流 429（免费档 20 次/分）")
        if resp.status_code >= 400:
            return FetchResult(success=False, url=url, reason=f"Jina HTTP {resp.status_code}")
        content = (resp.text or "").strip()
        limit = max_chars or self._max_content_chars
        return FetchResult(
            success=bool(content),
            url=url,
            content=content[:limit] if limit else content,
            provider="jina",
            reason="" if content else "Jina 返回空内容",
            fetched_at=time.time(),
        )

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client()
        return self._client
