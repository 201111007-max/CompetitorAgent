"""第 1 级抓取 provider — trafilatura 本地解析（设计文档 71 §3.4，默认路径）。

httpx 取 HTML（全程挂 ``_guarded_get`` 守卫）→ ``trafilatura.extract`` 抽取正文。
trafilatura 为可选 extra（``pip install -e .[search]``）：未安装时该级注册为
「不可用」（``available()=False``，链自动降为 2 级，见 doc 71 §7.3）。本地库、无 Key。
"""
from __future__ import annotations

import logging
import time

import httpx

from competitor_agent.collector.fetch import FetchProvider, FetchResult, _guarded_get

logger = logging.getLogger("competitor_agent.collector.fetch.trafilatura")

_DEFAULT_UA = "competitor-agent/0.1"


class TrafilaturaFetchProvider(FetchProvider):
    """trafilatura 本地解析抓取（毫秒级、无 Key；隐性失败由路由 ``_is_shell`` 接管）。"""

    source_provider = "trafilatura"

    def __init__(
        self,
        timeout: float = 20.0,
        user_agent: str = _DEFAULT_UA,
        max_content_chars: int = 8000,
        client: httpx.Client | None = None,
    ) -> None:
        self._timeout = timeout
        self._user_agent = user_agent
        self._max_content_chars = max_content_chars
        self._client = client

    def available(self) -> bool:
        try:
            import trafilatura  # noqa: F401
        except ImportError:
            return False
        return True

    def fetch(self, url: str, max_chars: int) -> FetchResult:
        try:
            import trafilatura
        except ImportError:
            return FetchResult(
                success=False,
                url=url,
                reason="trafilatura 未安装（运行 pip install -e .[search] 后启用）",
            )
        try:
            resp = _guarded_get(
                self._get_client(), url, {"User-Agent": self._user_agent}, self._timeout
            )
        except httpx.HTTPError as exc:
            return FetchResult(success=False, url=url, reason=f"HTTP 请求失败: {exc}")
        except Exception as exc:  # noqa: BLE001 - 含 URLError 守卫拦截
            return FetchResult(success=False, url=url, reason=f"请求被拦截: {exc}")
        if resp.status_code >= 400:
            return FetchResult(success=False, url=url, reason=f"HTTP {resp.status_code}")
        try:
            text = trafilatura.extract(
                resp.text, include_comments=False, include_tables=False, favor_precision=True
            )
            metadata = trafilatura.extract_metadata(resp.text)
        except Exception as exc:  # noqa: BLE001 - 提取异常视为该级失败，路由降级
            logger.warning("trafilatura.extract(%s) 失败: %s", url, exc)
            return FetchResult(success=False, url=url, reason=f"trafilatura 提取失败: {exc}")
        content = (text or "").strip()
        limit = max_chars or self._max_content_chars
        return FetchResult(
            success=bool(content),
            url=url,
            title=(metadata.title or "").strip() if metadata is not None else "",
            content=content[:limit] if limit else content,
            provider="trafilatura",
            reason="" if content else "trafilatura 未提取到正文",
            fetched_at=time.time(),
        )

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client()
        return self._client
