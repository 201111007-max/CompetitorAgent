"""抓取层抽象与降级路由（设计文档 71 §3.4/§4）——三级降级链。

- ``FetchResult``：统一抓取结果（成功/失败、命中层级 via、失败原因，不抛异常）；
- ``FetchProvider(ABC)``：各级 provider 基类（trafilatura→crawl4ai→jina_reader）；
- ``FetchRouter``：逐级尝试，命中即停；成功级写 ``FetchResult.provider``（via:）；
  隐性失败（``_is_shell``，fetch_policy）触发降级到下一级；
- ``build_fetch_router``：``FETCH_ENABLED=false`` → None（纯搜索模式短路）；
  否则按 ``cfg.fetch_fallback_chain`` 组链（crawl4ai 默认不在链中，browser_pool>0
  且 extra/浏览器就绪才插入第 2 级）。
- 全程挂 ``guard_http_url``（doc 41）：入口 + 逐跳重定向重校验（``_guarded_get``）。
"""
from __future__ import annotations

import logging
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from competitor_agent.config.loader import CollectorConfig
from competitor_agent.core.url_guard import guard_http_url

logger = logging.getLogger("competitor_agent.collector.fetch")

_MAX_REDIRECTS = 5


@dataclass
class FetchResult:
    """统一抓取结果（设计文档 71 §3.1）。``success=False`` 时 ``reason`` 必填人可读。"""

    success: bool
    url: str
    title: str = ""  # 页标题（尽力而为，可为空）
    content: str = ""  # 清洗后的正文（≤ fetch_max_chars）
    provider: str = ""  # 实际命中级："trafilatura"|"crawl4ai"|"jina"（via: 由此而来）
    reason: str = ""  # 失败原因（success=False 时必填）
    fetched_at: float = 0.0


class FetchProvider(ABC):
    """抓取 provider 抽象（设计文档 71 §3.4）：按降级顺序逐级尝试。"""

    #: 级名（via: 标注）
    source_provider: str = ""

    @abstractmethod
    def fetch(self, url: str, max_chars: int) -> FetchResult:
        """抓取 url 返回结果。失败返回 ``FetchResult(success=False, reason=...)`` 不抛异常。"""

    def available(self) -> bool:
        """构建期可用性（缺依赖/缺浏览器 → False，该级注册为「不可用」直接降级）。"""
        return True


class FetchRouter:
    """三级降级链（设计文档 71 §4.2/§4.3）。

    逐级尝试命中即停；成功且非空壳（``_is_shell``）→ 返回；否则记 fallback_event 降级。
    三级全失败 → 返回 ``FetchResult(success=False, reason=...)``（不抛，工具层 str 出口安全）。
    """

    def __init__(self, providers: list[FetchProvider]) -> None:
        self._providers = [p for p in providers if p.available()]

    @property
    def providers(self) -> list[FetchProvider]:
        return list(self._providers)

    @property
    def active_count(self) -> int:
        return len(self._providers)

    def fetch(self, url: str, max_chars: int) -> FetchResult:
        from competitor_agent.collector.fetch_policy import _is_shell

        attempted: list[str] = []
        for provider in self._providers:
            level = provider.source_provider or type(provider).__name__
            try:
                result = provider.fetch(url, max_chars=max_chars)
            except Exception as exc:  # noqa: BLE001 - provider 意外异常视为该级失败
                reason = f"{type(exc).__name__}: {exc}"
                attempted.append(f"{level}: {reason}")
                self._log_fallback(level, reason)
                continue
            if result.success and not _is_shell(result.content):
                if result.provider:
                    result.provider = level
                return result
            reason = result.reason or "空壳（隐性失败）"
            attempted.append(f"{level}: {reason}")
            self._log_fallback(level, reason)
        return FetchResult(
            success=False,
            url=url,
            reason="; ".join(attempted) or "无可用抓取 provider",
        )

    @staticmethod
    def _log_fallback(level: str, reason: str) -> None:
        logger.info(
            "fetch.fallback_event level=%s reason=%s",
            level, reason,
            extra={"fallback_event": f"fetch:→{level}", "trigger": reason[:120]},
        )


def build_fetch_router(cfg: CollectorConfig) -> FetchRouter | None:
    """路由构造（设计文档 71 §2.3/§3.4）：FETCH_ENABLED=false → None（纯搜索模式）。

    启用 → 按 ``cfg.fetch_fallback_chain`` 组链；crawl4ai 默认不在链中（可选启用，
    须 extra + 浏览器就绪且 ``browser_pool>0`` 才插入第 2 级），默认两级
    ``trafilatura → jina_reader``。全程挂 URL 守卫（doc 41）。
    """
    if not getattr(cfg, "fetch_enabled", True):
        return None
    from competitor_agent.collector.fetch_policy import _normalize_chain
    from competitor_agent.collector.fetch_providers.crawl4ai_fetch import Crawl4aiFetchProvider
    from competitor_agent.collector.fetch_providers.jina_fetch import JinaFetchProvider
    from competitor_agent.collector.fetch_providers.trafilatura_fetch import TrafilaturaFetchProvider

    chain = _normalize_chain(getattr(cfg, "fetch_fallback_chain", None))
    # crawl4ai 启用（browser_pool>0）但未显式列出 → 自动插入第 2 级（doc 71 §7.2）
    if getattr(cfg, "crawler_browser_pool", 0) > 0 and "crawl4ai" not in chain:
        insert_at = chain.index("trafilatura") + 1 if "trafilatura" in chain else 1
        chain.insert(insert_at, "crawl4ai")
    providers: list[FetchProvider] = []
    for name in chain:
        if name in ("trafilatura",):
            providers.append(
                TrafilaturaFetchProvider(
                    timeout=cfg.timeout_seconds,
                    user_agent=cfg.user_agent,
                    max_content_chars=cfg.fetch_max_chars,
                )
            )
        elif name == "crawl4ai":
            if getattr(cfg, "crawler_browser_pool", 0) > 0:
                providers.append(
                    Crawl4aiFetchProvider(
                        timeout=cfg.crawler_timeout,
                        headless=cfg.crawler_headless,
                        max_content_chars=cfg.fetch_max_chars,
                    )
                )
            else:
                logger.info("crawl4ai 未启用（crawler.browser_pool=0），链中跳过该级")
        elif name in ("jina", "jina_reader"):
            if getattr(cfg, "jina_reader_enabled", True):
                providers.append(
                    JinaFetchProvider(
                        timeout=cfg.timeout_seconds,
                        user_agent=cfg.user_agent,
                        max_content_chars=cfg.fetch_max_chars,
                    )
                )
            else:
                logger.info("jina_reader 未启用（jina_reader.enabled=false），链中跳过该级")
    if not providers:
        return None
    return FetchRouter(providers)


def _guarded_get(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    timeout: float,
    block_private: bool = True,
) -> httpx.Response:
    """带 URL 守卫（doc 41）的受限 GET：入口已校验，重定向逐跳重校验防 SSRF。

    返回最终响应；守卫拦截/重定向超限抛 ``URLError``；HTTP 错误不在此抛（调用方处理）。
    """
    current = guard_http_url(url) if block_private else url
    resp: httpx.Response | None = None
    for _ in range(_MAX_REDIRECTS + 1):
        resp = client.get(
            current,
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
        )
        if resp.status_code not in (301, 302, 303, 307, 308):
            break
        location = resp.headers.get("location")
        if not location:
            break
        current = urllib.parse.urljoin(current, location)
        if block_private:
            current = guard_http_url(current)
    assert resp is not None
    return resp
