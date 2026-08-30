"""第 2 级抓取 provider — crawl4ai 本地浏览器渲染（设计文档 71 §3.4/§4.4，可选）。

- **默认禁用**：``crawler.browser_pool>0`` 且 extra（``pip install -e .[crawl4ai]``）+
  浏览器就绪（``crawl4ai-setup``）才注册进链（``build_fetch_router`` 已处理）；
- **进程内单例复用**：模块级后台事件循环 + 懒构造 ``AsyncWebCrawler``，请求之间复用
  同一浏览器实例（避免每次降级冷启动）；空闲超时（``_SINGLETON_TTL``）强制重建；
- **异常重建**：浏览器崩溃 → 捕获重建一次性实例，记 ``crawl4ai.reset`` 日志（仅计数）；
- **构建期护栏**：未装 extra/浏览器 → ``available()=False``，该级注册「不可用」直接降级
  （doc 71 §7.3），不试图运行中拉浏览器。
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from competitor_agent.collector.fetch import FetchProvider, FetchResult
from competitor_agent.core.url_guard import URLError, guard_http_url

logger = logging.getLogger("competitor_agent.collector.fetch.crawl4ai")

_SINGLETON_TTL = 3600.0  # 浏览器单例空闲回收秒数（1h）

_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()  # _ensure_loop 双起保护
_crawler_lock = threading.Lock()  # 单例构造/重建保护
_arun_lock = threading.Lock()  # 浏览器单例 arun 串行化（并发调用不共享同一实例）
_crawler: Any = None
_crawler_created = 0.0


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """后台事件循环单例（daemon 线程），供 AsyncWebCrawler 长驻复用。"""
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            new_loop = asyncio.new_event_loop()
            threading.Thread(
                target=_run_loop, args=(new_loop,), daemon=True, name="crawl4ai-loop"
            ).start()
            _loop = new_loop
        return _loop


def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _get_crawler(headless: bool) -> Any:
    """懒构造 + 单例复用 + 空闲 TTL 重建（doc 71 §4.4）。"""
    global _crawler, _crawler_created
    now = time.time()
    with _crawler_lock:
        if _crawler is None or (now - _crawler_created) > _SINGLETON_TTL:
            if _crawler is not None:
                logger.warning("crawl4ai.reset reason=idle_ttl")
                _close_crawler(_crawler)
                _crawler = None
            from crawl4ai import AsyncWebCrawler

            _crawler = AsyncWebCrawler(headless=headless, verbose=False)
            _crawler_created = now
        return _crawler


def _close_crawler(crawler: Any) -> None:
    loop = _ensure_loop()
    try:
        fut = asyncio.run_coroutine_threadsafe(crawler.close(), loop)
        fut.result(timeout=10)
    except Exception:
        logger.debug("crawl4ai 浏览器关闭失败（忽略，重建一次性实例）", exc_info=True)


def _crawl_sync(url: str, headless: bool, timeout: float) -> tuple[str, str, str]:
    """在后台 loop 上执行一次 arun；返回 (markdown, html, title)。

    浏览器单例跨请求复用，并发 arun 用 ``_arun_lock`` 串行化（同实例不可并行导航）。
    """
    global _crawler
    loop = _ensure_loop()
    with _arun_lock:  # 构造 + 进入上下文 + arun 整体持锁，防并发双进上下文/双抓
        crawler = _get_crawler(headless)
        from crawl4ai import CrawlerRunConfig

        config = CrawlerRunConfig(verbose=False)

        async def _arun() -> Any:
            if not getattr(crawler, "_entered", False):
                await crawler.__aenter__()  # 首次进入上下文，浏览器常驻复用
                crawler._entered = True
            return await crawler.arun(url, config=config)

        try:
            fut = asyncio.run_coroutine_threadsafe(_arun(), loop)
            result = fut.result(timeout=max(10.0, float(timeout)))
        except Exception as exc:
            logger.warning("crawl4ai.reset reason=error %s", type(exc).__name__)
            with _crawler_lock:
                if _crawler is not None:
                    _close_crawler(_crawler)
                    _crawler = None
            raise
    if result is None:
        return "", "", ""
    metadata = getattr(result, "metadata", None)
    title = str(getattr(metadata, "title", "") or "") if metadata is not None else ""
    return (
        str(getattr(result, "markdown", "") or ""),
        str(getattr(result, "html", "") or ""),
        title,
    )


class Crawl4aiFetchProvider(FetchProvider):
    """crawl4ai 浏览器渲染抓取（秒级；JS 重页兜底；本地库、无 Key、默认关）。"""

    source_provider = "crawl4ai"

    def __init__(
        self,
        timeout: float = 30.0,
        headless: bool = True,
        max_content_chars: int = 8000,
    ) -> None:
        self._timeout = timeout
        self._headless = headless
        self._max_content_chars = max_content_chars

    def available(self) -> bool:
        try:
            import crawl4ai  # noqa: F401
        except ImportError:
            return False
        return True

    def fetch(self, url: str, max_chars: int) -> FetchResult:
        # P0 防御（doc 71 §3.4「全程挂 URL 守卫」）：入口已校验初始 URL，此处兜底再校验；
        # 注意：浏览器导航会自行跟随重定向（重定向目标不逐跳重校验）——启用该级时
        # 此为已知限制（见 doc 71 §11 风险表，默认 browser_pool=0 关闭）。
        try:
            guard_http_url(url)
        except URLError as exc:
            return FetchResult(success=False, url=url, reason=f"URL 被安全守卫拦截: {exc}")
        try:
            markdown, html, title = _crawl_sync(url, self._headless, self._timeout)
        except Exception as exc:  # noqa: BLE001 - 抓取失败降级到下一级
            return FetchResult(
                success=False,
                url=url,
                reason=f"crawl4ai 抓取失败: {type(exc).__name__}: {exc}",
            )
        content = (markdown or html or "").strip()
        limit = max_chars or self._max_content_chars
        return FetchResult(
            success=bool(content),
            url=url,
            title=title,
            content=content[:limit] if limit else content,
            provider="crawl4ai",
            reason="" if content else "crawl4ai 未提取到内容",
            fetched_at=time.time(),
        )
