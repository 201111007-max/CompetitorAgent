"""Search-related MCP tools — async versions.

Provides tools for searching Dota 2 history via SerpApi with full-text
extraction, using httpx.AsyncClient instead of requests.
"""

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from dota_helper.mcp_server.server import mcp
from dota_helper.secret_vault import vault

logger = logging.getLogger(__name__)

from dota_helper.mcp_server.helpers.text_processing import fetch_fulltext

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
TIMEOUT: int = 30


@mcp.tool()
async def search_dota_history(
    query: str,
    num_results: int = 5,
    include_liquipedia: bool = True,
    sites: Optional[List[str]] = None,
    fetch_fulltext: bool = True,  # noqa: ARG001  -- shadowing is intentional to match API
    fulltext_max_chars: int = 8000,
) -> str:
    """
    通过 SerpApi 搜索 Dota 相关历史信息并获取网页全文

    Args:
        query: 搜索关键词
        num_results: 返回结果数量（1-10），默认 5
        include_liquipedia: 是否包含 Liquipedia 站点，默认 True
        sites: 限定搜索站点列表，如 ["liquipedia.net/dota2", "gosugamers.net"]
        fetch_fulltext: 是否获取网页全文内容，默认 True
        fulltext_max_chars: 全文最大字符数（<=0 表示不获取），默认 8000

    Returns:
        搜索结果列表，包括标题、摘要、链接和可选全文
    """
    logger.info("search_dota_history called with: query=%s, num_results=%s, include_liquipedia=%s, sites=%s, fetch_fulltext=%s, fulltext_max_chars=%s", query, num_results, include_liquipedia, sites, fetch_fulltext, fulltext_max_chars)

    api_key = vault.get("SERPAPI_API_KEY", owner="search_tools") or ""
    if not api_key:
        return "❌ 未配置 SERPAPI_API_KEY，无法使用搜索工具"

    query = (query or "").strip()
    if not query:
        return "❌ query 不能为空"

    try:
        limit = int(num_results)
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, min(limit, 10))
    try:
        max_chars = int(fulltext_max_chars)
    except (TypeError, ValueError):
        max_chars = 8000
    max_chars = max(0, min(max_chars, 50000))

    default_sites = [
        "liquipedia.net/dota2",
        "gosugamers.net",
        "dotabuff.com",
    ]
    site_filters: List[str] = []
    if sites:
        site_filters.extend([s.strip() for s in sites if isinstance(s, str) and s.strip()])
    else:
        site_filters.extend(default_sites)
    if include_liquipedia and "liquipedia.net/dota2" not in site_filters:
        site_filters.append("liquipedia.net/dota2")
    site_filters = list(dict.fromkeys(site_filters))

    search_query = query
    if site_filters:
        site_clause = " OR ".join([f"site:{s}" for s in site_filters])
        search_query = f"{query} ({site_clause})"
    logger.info("search_dota_history: SerpApi query=%s", search_query)
    used_query = search_query
    used_site_filters = site_filters[:]
    fallback_used = False

    async def _serpapi_request(q: str, hl: str) -> Dict[str, Any]:
        params = {
            "engine": "google",
            "q": q,
            "num": limit,
            "hl": hl,
            "api_key": api_key,
        }
        async with httpx.AsyncClient(timeout=TIMEOUT) as http_client:
            response = await http_client.get(SERPAPI_ENDPOINT, params=params)
            response.raise_for_status()
            return response.json()

    try:
        data = await _serpapi_request(search_query, "zh-CN")
        logger.info("search_dota_history: fetched SerpApi data successfully (zh-CN)")
    except httpx.HTTPStatusError as exc:
        logger.warning("search_dota_history: SerpApi HTTP error: %s", exc)
        return f"❌ SerpApi 请求失败: {exc}"
    except httpx.RequestError as exc:
        logger.warning("search_dota_history: SerpApi request error: %s", exc)
        return f"❌ SerpApi 请求失败: {exc}"
    except ValueError:
        logger.warning("search_dota_history: SerpApi returned non-JSON response")
        return "❌ SerpApi 返回非 JSON 响应"

    if isinstance(data, dict) and data.get("error"):
        error_message = str(data["error"])
        logger.warning("search_dota_history: SerpApi returned error: %s", error_message)
        if "hasn't returned any results" in error_message and site_filters:
            logger.info("search_dota_history: falling back from Chinese to English search")
            try:
                data = await _serpapi_request(query, "en")
                used_query = query
                used_site_filters = []
                fallback_used = True
                logger.info("search_dota_history: fallback search succeeded")
            except httpx.HTTPStatusError as exc:
                logger.warning("search_dota_history: fallback SerpApi HTTP error: %s", exc)
                return f"❌ SerpApi 请求失败: {exc}"
            except httpx.RequestError as exc:
                logger.warning("search_dota_history: fallback SerpApi request error: %s", exc)
                return f"❌ SerpApi 请求失败: {exc}"
            except ValueError:
                logger.warning("search_dota_history: fallback SerpApi returned non-JSON response")
                return "❌ SerpApi 返回非 JSON 响应"
        else:
            return f"❌ SerpApi 错误: {data['error']}"

    results = data.get("organic_results") if isinstance(data, dict) else None
    if not results:
        if not isinstance(data, dict):
            logger.warning("search_dota_history: unexpected data type=%s", type(data).__name__)
        if site_filters:
            logger.info("search_dota_history: no results, falling back from Chinese to English search")
            try:
                data = await _serpapi_request(query, "en")
                used_query = query
                used_site_filters = []
                fallback_used = True
                logger.info("search_dota_history: fallback search succeeded")
            except httpx.HTTPStatusError as exc:
                logger.warning("search_dota_history: fallback SerpApi HTTP error: %s", exc)
                return f"❌ SerpApi 请求失败: {exc}"
            except httpx.RequestError as exc:
                logger.warning("search_dota_history: fallback SerpApi request error: %s", exc)
                return f"❌ SerpApi 请求失败: {exc}"
            except ValueError:
                logger.warning("search_dota_history: fallback SerpApi returned non-JSON response")
                return "❌ SerpApi 返回非 JSON 响应"
            results = data.get("organic_results") if isinstance(data, dict) else None
        if not results:
            logger.warning("search_dota_history: no search results found")
            return "⚠️ 未找到搜索结果"

    payload = {
        "query": query,
        "search_query": used_query,
        "site_filters": used_site_filters,
        "fallback_used": fallback_used,
        "fulltext_enabled": bool(fetch_fulltext),
        "fulltext_max_chars": max_chars,
        "results": [],
    }

    for item in results[:limit]:
        link = str(item.get("link", ""))
        if not link:
            continue
        result = {
            "title": item.get("title"),
            "snippet": item.get("snippet"),
            "link": link,
            "source": item.get("source"),
            "date": item.get("date") or item.get("published_date"),
        }
        if fetch_fulltext:
            logger.info("search_dota_history: fetching fulltext for link=%s", link)
            full_text, err, truncated = fetch_fulltext(link, max_chars=max_chars)
            if err:
                result["full_text_error"] = err
            else:
                result["full_text"] = full_text
                result["full_text_chars"] = len(full_text) if full_text else 0
                if truncated:
                    result["full_text_truncated"] = True
        payload["results"].append(result)

    logger.info("search_dota_history: completed with %d results", len(payload["results"]))
    return json.dumps(payload, ensure_ascii=False, indent=2)
