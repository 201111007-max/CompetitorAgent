"""DuckDuckGo 免费搜索 provider（设计文档 71 §3.3）——无 Key、纯 httpx 直连。

实现：GET ``https://html.duckduckgo.com/html/``（DDG HTML 界面端点，非官方接口，
见 doc 71 §11 风险 1）→ bs4 解析 ``.result`` 块（``.result__a`` 标题/链接 +
``.result__snippet`` 摘要）；结果 href 为 DDG 跳转链接（``/l/?uddg=...``）时还原为
真实目标 URL。可注入 ``httpx.Client``（测试用 MockTransport 拦截）。

失败分类（doc 71 §4.1）：HTTP 202 / 响应体含 ``anomaly`` / 429 → ``SearchError(kind="rate_limited")``；
连接/超时/5xx → ``kind="network"``；其他 4xx → ``kind="http"``；解析失败 → ``kind="parse"``。
"""
from __future__ import annotations

import logging
import urllib.parse

import httpx

from competitor_agent.collector.search import SearchError, SearchHit, SearchProvider

logger = logging.getLogger("competitor_agent.collector.search.ddg")

_DDG_HTML_URL = "https://html.duckduckgo.com/html/"
_ANOMALY_MARKER = "anomaly"
_MAX_RESULTS_CAP = 20


class DuckDuckGoSearchProvider(SearchProvider):
    """DDG HTML 端点搜索（免 Key 免费主力；非官方接口，失败抛 SearchError 带 kind）。"""

    source_engine = "duckduckgo"

    def __init__(
        self,
        timeout: float = 20.0,
        user_agent: str = "competitor-agent/0.1",
        client: httpx.Client | None = None,
    ) -> None:
        self._timeout = timeout
        self._user_agent = user_agent
        self._client = client

    def search(self, query: str, max_results: int = 8) -> list[SearchHit]:
        headers = {"User-Agent": self._user_agent}
        params = {"q": query, "s": 0}
        try:
            resp = self._get_client().get(
                _DDG_HTML_URL, params=params, headers=headers, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise SearchError(f"DDG 搜索请求失败: {exc}", kind="network") from exc

        status = resp.status_code
        body_head = (resp.text or "")[:1000].lower()
        if status == 202 or _ANOMALY_MARKER in body_head:
            raise SearchError("DDG 触发限流/异常响应（202/anomaly）", kind="rate_limited")
        if status == 429:
            raise SearchError("DDG 限流 HTTP 429", kind="rate_limited")
        if status >= 500:
            raise SearchError(f"DDG 搜索 HTTP {status}", kind="network")
        if status >= 400:
            raise SearchError(f"DDG 搜索 HTTP {status}: {resp.text[:200]}", kind="http")
        try:
            return self._parse_html(resp.text, max_results)
        except SearchError:
            raise
        except Exception as exc:
            raise SearchError(f"DDG 响应解析失败: {exc}", kind="parse") from exc

    def _parse_html(self, html: str, max_results: int) -> list[SearchHit]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        limit = max(1, min(int(max_results or 8), _MAX_RESULTS_CAP))
        hits: list[SearchHit] = []
        for node in soup.select(".result")[:limit]:
            anchor = node.select_one(".result__a")
            if anchor is None:
                continue
            title = anchor.get_text(strip=True)
            href = str(anchor.get("href") or "").strip()
            url = _decode_ddg_link(href)
            if not title or not url:
                continue
            snippet_node = node.select_one(".result__snippet")
            snippet = snippet_node.get_text(strip=True) if snippet_node else ""
            hits.append(SearchHit(title=title, url=url, snippet=snippet))
        return hits

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client()
        return self._client


def _decode_ddg_link(href: str) -> str:
    """DDG HTML 结果 href 多为 ``//duckduckgo.com/l/?uddg=<urlencoded>&rut=...``。

    还原为真实目标 URL；普通绝对 http(s) 链接原样返回；无法识别返回空串（剔除）。
    """
    href = href.strip()
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if parsed.scheme not in ("http", "https"):
        return ""
    host = parsed.hostname or ""
    if host.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        uddg = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
        return urllib.parse.unquote(uddg).strip() if uddg else ""
    return href
