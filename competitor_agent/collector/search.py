"""搜索提供方 — 真实 Tavily 搜索接入（设计文档 66 §3.1）

落实 doc 61 声称但从未落地的搜索链：``SearchProvider`` 策略抽象 +
``TavilySearchProvider``（httpx POST https://api.tavily.com/search）+ 装配层
零入口注入 ``web_tool``。Key 只读环境变量 ``TAVILY_API_KEY`` 不落盘；
无 Key/未启用/失败 → 降级返回空（不编造，守 doc 47）。
"""
from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from competitor_agent.config.loader import CollectorConfig
from competitor_agent.core.competitor_discoverer import json_loads_array
from competitor_agent.llm.client import LLMClient

logger = logging.getLogger("competitor_agent.collector.search")

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_TAVILY_KEY_ENV = "TAVILY_API_KEY"
_DEFAULT_USER_AGENT = "competitor-agent/0.1"

# 候选归纳 prompt（LLM 从搜索 hits 归纳 name/home/pricing/docs）
_LLM_CANDIDATES_PROMPT = (
    "你是竞品发现助手。下面是从搜索引擎抓取到的竞品相关信息。"
    "请归纳出候选竞品清单，只输出 JSON 数组，不要其他文字。"
    'JSON 格式：[{"name": "规范名", "home": "官网", "pricing": "定价页", "docs": "文档"}, ...]。'
    "name 用英文小写+连字符；无法确定的链接给空字符串；不属于竞品的噪声条目剔除。"
)


class SearchError(RuntimeError):
    """搜索失败（网络/非 2xx/响应异常）——上层捕获后降级返回空，不编造。"""


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str


class SearchProvider(ABC):
    """搜索提供方抽象（对齐 doc 66/67 的策略模式）。"""

    @abstractmethod
    def search(self, query: str, max_results: int = 8) -> list[SearchHit]:
        """搜索 query，返回 ≤max_results 条命中；失败抛异常（上层降级不编造）。"""


class TavilySearchProvider(SearchProvider):
    """httpx POST https://api.tavily.com/search（Bearer 鉴权）。

    响应 results[] 映射 title/url/content → SearchHit；非 2xx/超时/网络错 → 抛
    可重试异常（上层降级返回空，不编造）。可注入 client 便于测试。
    """

    def __init__(
        self,
        api_key: str,
        timeout: float = 20.0,
        user_agent: str = _DEFAULT_USER_AGENT,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._user_agent = user_agent
        self._client = client

    def search(self, query: str, max_results: int = 8) -> list[SearchHit]:
        payload = {
            "query": query,
            "search_depth": "basic",
            "max_results": max(1, min(int(max_results), 20)),
            "include_answer": False,
            "include_raw_content": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "User-Agent": self._user_agent,
        }
        try:
            resp = self._get_client().post(
                _TAVILY_SEARCH_URL, json=payload, headers=headers, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise SearchError(f"Tavily 搜索请求失败: {exc}") from exc
        if resp.status_code >= 400:
            raise SearchError(f"Tavily 搜索 HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise SearchError("Tavily 搜索响应非 JSON") from exc
        hits: list[SearchHit] = []
        for item in data.get("results") or []:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            hits.append(
                SearchHit(
                    title=str(item.get("title") or "").strip(),
                    url=url,
                    snippet=str(item.get("content") or "").strip(),
                )
            )
        return hits

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client()
        return self._client


def build_search_provider(cfg: CollectorConfig) -> SearchProvider | None:
    """cfg.search_provider=="tavily" 且环境变量 TAVILY_API_KEY 存在 → TavilySearchProvider。

    其他/缺 Key/未知名 → None（不启用，保持现状——web_search 走可读提示、
    DISCOVERY 走空候选降级）。
    """
    if getattr(cfg, "search_provider", "") != "tavily":
        return None
    api_key = os.environ.get(_TAVILY_KEY_ENV, "").strip()
    if not api_key:
        return None
    return TavilySearchProvider(api_key, timeout=cfg.timeout_seconds)


def web_search_candidates(
    task: str,
    provider: SearchProvider | None,
    llm: LLMClient | None,
    max_results: int = 8,
) -> list[dict[str, Any]]:
    """hits → LLM 归纳为 [{"name","home","pricing","docs"}]（DISCOVERY 候选枚举专用）。

    空/搜索失败/LLM 畸形/LLM 不可用 → []（不编造，守 doc 47）。
    """
    if provider is None or llm is None:
        return []
    try:
        hits = provider.search(task, max_results=max_results)
    except SearchError:
        logger.warning("候选竞品搜索失败: query=%r", task, exc_info=True)
        return []
    if not hits:
        return []
    try:
        text = llm.complete(
            messages=[
                {"role": "system", "content": _LLM_CANDIDATES_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        [{"title": h.title, "url": h.url, "snippet": h.snippet} for h in hits],
                        ensure_ascii=False,
                    ),
                },
            ]
        )
        return json_loads_array(text)
    except Exception:
        logger.warning("候选竞品 LLM 归纳失败: query=%r", task, exc_info=True)
        return []


__all__ = [
    "SearchError",
    "SearchHit",
    "SearchProvider",
    "TavilySearchProvider",
    "build_search_provider",
    "web_search_candidates",
]
