"""MCP Server — 网页采集工具（设计文档 71：搜索/抓取两层架构，契约 str→str）

- ``web_search``：经 ``build_search_router``（DDG 免费主力 + 可选 Tavily 降级池），
  文本块带 ``·via:{engine}·{time}`` 层级标注；无 provider/失败 → 可读提示，不编造。
- ``web_extract``：原地升级走三级降级链（``build_fetch_router``：
  trafilatura→crawl4ai→jina_reader），``via: {级}`` 标注 + 单跑去重/上限（FetchPolicy）
  + 分级磁盘缓存（FetchCache）；``FETCH_ENABLED=false`` → 固定禁用提示。
"""
from __future__ import annotations

import logging
import urllib.parse

import httpx

from competitor_agent.collector.fetch import FetchResult, FetchRouter, build_fetch_router
from competitor_agent.collector.fetch_cache import FetchCache
from competitor_agent.collector.fetch_policy import FetchPolicy
from competitor_agent.collector.search import SearchError, SearchHit, build_search_router
from competitor_agent.config.loader import CollectorConfig, load_config
from competitor_agent.core.url_guard import URLError, guard_http_url

logger = logging.getLogger("competitor_agent.mcp_server.tools.web_tools")

_MAX_REDIRECTS = 5

_default_cache: FetchCache | None = None


def _cache(collector: CollectorConfig) -> FetchCache:
    """模块级共享缓存（跨调用/跨进程持久化；TTL 取配置，首次构造定）。"""
    global _default_cache
    if _default_cache is None:
        _default_cache = FetchCache(
            search_ttl_hours=collector.cache_ttl_search_hours,
            fetch_ttl_days=collector.cache_ttl_fetch_days,
        )
    return _default_cache


def _format_hit(hit: SearchHit) -> str:
    """单条搜索命中文本块：`标题\\nURL\\n摘要·via:{engine}·{time}`（doc 71 §3.2）。"""
    meta = ""
    if hit.source_engine or hit.fetched_at:
        engine = hit.source_engine or "?"
        ts = f"{hit.fetched_at:.0f}" if hit.fetched_at else "?"
        meta = f"·via:{engine}·{ts}"
    return f"{hit.title}\n{hit.url}\n{hit.snippet}{meta}"


def web_search(query: str, max_results: int = 5) -> str:
    """搜索竞品相关信息（DDG 免费主力；可选 Tavily 增强降级；未启用/失败 → 可读提示）。

    - 经 ``build_search_router(load_config().collector)``（enable_external_sources 主门控）；
    - router 为空 → 可读提示（保持「搜索功能未启用」文案，供测试/回灌断言）；
    - 命中 → 逐条 `标题\\nURL\\n摘要·via:{engine}·{time}` 文本块；
    - 空 → 「未搜索到…」；全部失败 → 「搜索暂不可用: …」（不编造，守 doc 47）。
    """
    try:
        router = build_search_router(load_config().collector)
    except Exception:
        logger.warning("build_search_router 失败", exc_info=True)
        router = None
    if router is None:
        return (
            f"搜索功能未启用：需要开启 enable_external_sources（联网主开关）。\n"
            f"查询: {query}\n"
            f"建议: 使用 web_extract 直接采集已知竞品官网。"
        )
    try:
        hits = router.search(query, max_results=max_results)
    except SearchError as exc:
        logger.warning(
            "web_search(%s) 失败 kind=%s: %s", query, exc.kind, exc,
            extra={"kind": exc.kind, "rate_limited": exc.kind == "rate_limited"},
        )
        return f"搜索暂不可用: {exc}"
    if not hits:
        return f"未搜索到与 {query!r} 相关的结果。"
    return "\n\n".join(_format_hit(h) for h in hits)


def _format_fetch(result: FetchResult, max_chars: int) -> str:
    """抓取成功文本：顶部 `via: {级}` 一行元信息 + 正文（doc 71 §4.3）。"""
    body = result.content
    if max_chars and len(body) > max_chars:
        body = body[:max_chars] + "…（截断）"
    if result.provider:
        return f"via: {result.provider}\n{body}"
    return body


def web_extract(url: str, selector: str = "") -> str:
    """采集指定 URL 的网页内容（三层降级链；URL 过安全守卫防 SSRF）。

    - ``selector`` 非空 → 走 CSS 选择器抽取（兼容旧 bs4 行为）；
    - 其余 → ``build_fetch_router``（FETCH_ENABLED=false → 固定禁用提示）；
    - 成功 → 正文 + ``via: {级}``；三级全败 → 「抓取失败: {reason}」（不抛）；
    - 单跑去重 + 上限（FetchPolicy）；分级磁盘缓存（FetchCache）。

    签名保持 ``(url, selector)``（MCP 由签名反射 schema，doc 71 决策②），
    内部策略注入走 ``_web_extract_impl``（测试用）。
    """
    return _web_extract_impl(url, selector=selector)


def _web_extract_impl(
    url: str,
    selector: str = "",
    max_chars: int = 0,
    *,
    fetch_policy: FetchPolicy | None = None,
    fetch_router: FetchRouter | None = None,
    fetch_cache: FetchCache | None = None,
) -> str:
    """web_extract 真实实现（可注入 per-run FetchPolicy / 抓取 router / 磁盘缓存）。"""
    collector = load_config().collector
    if max_chars <= 0:
        max_chars = collector.fetch_max_chars
    try:
        current = guard_http_url(url) if collector.block_private_urls else url
    except URLError as exc:
        return f"⚠ URL 被安全守卫拦截: {exc}"

    if selector:
        return _extract_with_selector(current, selector, max_chars, collector)

    if not collector.fetch_enabled:
        return "抓取层已禁用（FETCH_ENABLED=false）。仅可依赖搜索摘要。"

    router = fetch_router if fetch_router is not None else build_fetch_router(collector)
    if router is None:
        return "抓取失败: 无可用抓取 provider（未启用任何抓取级）"

    policy = fetch_policy if fetch_policy is not None else FetchPolicy(
        max_per_run=collector.fetch_max_per_run
    )
    cache = fetch_cache if fetch_cache is not None else _cache(collector)

    # 1) 同 run 去重：不重抓、不计上限
    kind, note = policy.get(current)
    if kind == "cached":
        return _format_fetch(note, max_chars)
    # 2) 磁盘缓存（7d）先于单跑上限判定：命中缓存不重抓、不计上限（doc 71 §6.1）
    cached = cache.get_fetch(current)
    if cached is not None and cached.success:
        return _format_fetch(cached, max_chars)
    # 3) 单跑上限（仅实际抓取计数）
    if kind == "limit":
        return note

    result = router.fetch(current, max_chars)
    if result.success:
        result.url = current
        cache.set_fetch(result)
        policy.record(current, result)
        return _format_fetch(result, max_chars)
    return f"抓取失败: {result.reason}"


def _extract_with_selector(
    url: str, selector: str, max_chars: int, collector: CollectorConfig
) -> str:
    """CSS 选择器抽取（设计文档 71 §3.2 保留旧行为）：guarded GET + bs4 select。"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = None
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            resp = httpx.get(
                current,
                headers=headers,
                timeout=collector.timeout_seconds,
                follow_redirects=False,
            )
            if resp.status_code not in (301, 302, 303, 307, 308):
                break
            location = resp.headers.get("location")
            if not location:
                break
            current = urllib.parse.urljoin(current, location)
            if collector.block_private_urls:
                current = guard_http_url(current)
        assert resp is not None
        resp.raise_for_status()
    except URLError as exc:
        return f"⚠ URL 被安全守卫拦截: {exc}"
    except httpx.HTTPStatusError as exc:
        return f"⚠ HTTP {exc.response.status_code}: {url}"
    except httpx.RequestError as exc:
        return f"⚠ 请求失败: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"⚠ 采集异常: {exc}"
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return "⚠ 采集异常: 缺少依赖 bs4（解析网页需要）"
    try:
        soup = BeautifulSoup(resp.text, "lxml")
        elements = soup.select(selector)
        text = "\n".join(el.get_text(strip=True) for el in elements)
    except Exception as exc:  # noqa: BLE001
        logger.warning("web_extract 选择器解析异常: %s", exc)
        return f"⚠ 选择器解析异常: {exc}"
    if len(text) > max_chars:
        text = text[:max_chars] + "…（截断）"
    return text or f"⚠ 未从 {url} 提取到内容"
