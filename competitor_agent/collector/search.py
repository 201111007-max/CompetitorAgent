"""搜索提供方 — 免费主力 + 可选付费增强两层架构（设计文档 71）

- doc 66/69 的 ``TavilySearchProvider``（httpx POST https://api.tavily.com/search）保留
  为**可选付费增强**；新增 ``DuckDuckGoSearchProvider``（免费主力，无 Key 恒可用）；
- ``build_search_router`` 为**唯一构造入口**：enable_external_sources 主门控 + DDG 主力
  + TAVILY_API_KEY 存在时追加 Tavily 降级池（Key 只读环境变量不落盘）；
- ``build_search_provider`` 保留为向后兼容薄包装（doc 71 决策⑥，8 调用点/16 单测不破）；
- 装配层零入口注入 ``web_tool``；无 Key/未启用/失败 → 降级返回空（不编造，守 doc 47）。
"""
from __future__ import annotations

import json
import logging
import os
import time
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
    """搜索失败（网络/非 2xx/响应异常）——上层捕获后降级返回空，不编造。

    ``kind`` 区分失败类别（设计文档 71 §4.1）：``"network"``（连接/超时/5xx）、
    ``"rate_limited"``（429 / DDG 202-anomaly）、``"http"``（其他 4xx）、``"parse"``
    （响应解析失败）。日志按 kind 分别计数，供降级率统计。
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str = "network",
        **kw: Any,
    ) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    source_engine: str = ""  # 设计文档 71 §3.1："duckduckgo" / "tavily"（路由逐条标注实际命中引擎）
    fetched_at: float = 0.0  # epoch 秒；0 表示未记录（旧 provider 兼容）


class SearchProvider(ABC):
    """搜索提供方抽象（对齐 doc 66/67 的策略模式）。"""

    #: 引擎标识（设计文档 71 §3.3）：路由据此标注 SearchHit.source_engine
    source_engine: str = ""

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

    source_engine = "tavily"  # 路由据此标注实际命中引擎（设计文档 71 §3.3）

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
    DISCOVERY 走空候选降级）。doc 71 决策⑥：向后兼容薄包装，行为与 doc 66 逐位一致；
    新装配一律走 ``build_search_router``。
    """
    if getattr(cfg, "search_provider", "") != "tavily":
        return None
    api_key = os.environ.get(_TAVILY_KEY_ENV, "").strip()
    if not api_key:
        return None
    return TavilySearchProvider(api_key, timeout=cfg.timeout_seconds)


class SearchRouter(SearchProvider):
    """主力 + 降级池（设计文档 71 §3.3/§4.1）：主调用成功命中即返回。

    - 主力返回**非空** hits → 直接返回（不触发降级）；主力抛 ``SearchError`` 或返回
      空结果 → 记降级事件，依次尝试降级池（Tavily 增强可能更全）。
    - 逐条用 ``dataclasses.replace`` 标注实际命中引擎 ``source_engine`` 与时间
      ``fetched_at``（旧 provider 返回的默认空字段由路由补全，无需改 provider）。
    - 全部 provider 均抛错 → 抛最后一个 ``SearchError``（含 ``kind``，供日志区分
      限流/网络）；全部为空 → 返回空列表（上层报「未搜索到」，不编造）。
    """

    source_engine = "router"

    def __init__(self, providers: list[SearchProvider]) -> None:
        self._providers = list(providers)

    def search(self, query: str, max_results: int = 8) -> list[SearchHit]:
        last_err: SearchError | None = None
        for provider in self._providers:
            engine = getattr(provider, "source_engine", "") or type(provider).__name__
            try:
                hits = provider.search(query, max_results=max_results)
            except SearchError as exc:
                last_err = exc
                logger.warning(
                    "search.fallback_event engine=%s kind=%s msg=%s",
                    engine, exc.kind, exc,
                    extra={"fallback_event": f"search:→{engine}", "kind": exc.kind,
                           "degraded_from": engine},
                )
                continue
            if not hits:
                continue  # 空结果也尝试下一级（增强可能更全）
            return [self._stamp(h, engine) for h in hits]
        if last_err is not None:
            raise last_err
        return []

    @staticmethod
    def _stamp(hit: SearchHit, engine: str) -> SearchHit:
        return SearchHit(
            title=hit.title,
            url=hit.url,
            snippet=hit.snippet,
            source_engine=hit.source_engine or engine,
            fetched_at=hit.fetched_at or time.time(),
        )


def build_search_router(cfg: CollectorConfig) -> SearchRouter | None:
    """路由构造（设计文档 71 §2.2）——唯一装配入口。

    - **主门控**：``enable_external_sources=false`` → None（2026-08-30 评审确认，
      含 CLI/MCP 直达路径——否则切 DDG 默认后无网络用例会真实联网）。
    - 主力：``search_provider`` 空/"duckduckgo" → DDG（免 Key 恒可用）；
      ``"tavily"`` → 需 ``TAVILY_API_KEY``，缺 Key 回落 DDG（不再静默不可用）。
    - 付费增强（可选降级）：``TAVILY_API_KEY`` 存在且主力不是 Tavily → 追加 Tavily
      为降级池；Key 缺失 → 自动只留免费主力（注册表天然防呆）。
    - 返回的 router 永不抛「无可用 provider」：DDG 兜底，至少一个在。
    """
    if not getattr(cfg, "enable_external_sources", False):
        return None
    from competitor_agent.collector.search_providers.ddg import DuckDuckGoSearchProvider

    api_key = os.environ.get(_TAVILY_KEY_ENV, "").strip()
    tavily: TavilySearchProvider | None = None
    if api_key:
        tavily = TavilySearchProvider(api_key, timeout=cfg.timeout_seconds)

    primary_name = (getattr(cfg, "search_provider", "") or "").strip().lower()
    providers: list[SearchProvider] = []
    if primary_name in ("", "duckduckgo"):
        providers.append(DuckDuckGoSearchProvider(timeout=cfg.timeout_seconds, user_agent=cfg.user_agent))
    elif primary_name == "tavily":
        if tavily is not None:
            providers.append(tavily)
        else:
            logger.warning("search_provider=tavily 但缺 %s，回落 duckduckgo", _TAVILY_KEY_ENV)
            providers.append(DuckDuckGoSearchProvider(timeout=cfg.timeout_seconds, user_agent=cfg.user_agent))
    else:
        logger.warning("未知 search_provider=%r，回落 duckduckgo", primary_name)
        providers.append(DuckDuckGoSearchProvider(timeout=cfg.timeout_seconds, user_agent=cfg.user_agent))

    if tavily is not None and providers[0] is not tavily:
        providers.append(tavily)
    return SearchRouter(providers)


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
    "SearchRouter",
    "TavilySearchProvider",
    "build_search_provider",
    "build_search_router",
    "web_search_candidates",
]
