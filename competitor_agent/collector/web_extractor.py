"""WebExtractor — 官网/文档页抓取与清洗（requests + BeautifulSoup）

M1 不做 Playwright；SPA 页面由降级链处理（返回 degraded Observation）。
实现 ICompetitorDataSource 契约。
"""
from __future__ import annotations

import logging

import httpx

from competitor_agent.domain_types.enums import ObservationStatus
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation, SourceEvidence
from competitor_agent.interfaces.context import SourceContext
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError

logger = logging.getLogger("competitor_agent.collector.web_extractor")

_BLOCKED_MARKERS = ("captcha", "access denied", "not allowed", "403")

_SKIP_TAGS = {"script", "style", "noscript", "svg", "head", "nav", "footer"}


class WebExtractor:
    """基于 httpx + BeautifulSoup 的静态页抓取器"""

    def __init__(
        self,
        timeout: float = 20.0,
        user_agent: str = "competitor-agent/0.1",
        max_retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        self._timeout = timeout
        self._user_agent = user_agent
        self._max_retries = max_retries
        # 可注入 client（测试用 MockTransport），默认共享一个懒加载 client
        self._client = client

    @property
    def source_name(self) -> str:
        return "web_extractor"

    def is_available(self) -> bool:
        return True

    def fetch(self, gap: InfoGap, context: SourceContext) -> Observation:
        url = str(context.kwargs.get("url", ""))
        if not url:
            raise DataSourceUnavailableError(f"缺少抓取 URL: gap={gap.field}")

        content = self._get_content(url)
        if content is None:
            raise DataSourceUnavailableError(f"无法抓取 {url}")

        text = self._clean(content)
        evidence = SourceEvidence(
            source_name="web_extractor",
            url=url,
            content_hash=SourceEvidence.compute_hash(text),
            trust_level=0.9,
        )
        status = ObservationStatus.OK if len(text) > 50 else ObservationStatus.DEGRADED
        return Observation(
            gap_field=gap.field,
            source="web_extractor",
            raw_text=text,
            evidence=evidence,
            status=status,
        )

    def _get_content(self, url: str) -> str | None:
        headers = {"User-Agent": self._user_agent}
        last_err: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                client = self._client or self._get_client()
                resp = client.get(url, headers=headers, timeout=self._timeout, follow_redirects=True)
                if resp.status_code >= 400:
                    logger.warning("HTTP %s for %s (attempt %d)", resp.status_code, url, attempt)
                    last_err = DataSourceUnavailableError(f"HTTP {resp.status_code}")
                    continue
                return resp.text
            except httpx.HTTPError as exc:
                logger.warning("抓取 %s 失败: %s", url, exc)
                last_err = exc
        raise DataSourceUnavailableError(f"重试 {self._max_retries} 次仍失败: {url}") from last_err

    def _get_client(self) -> httpx.Client:
        return httpx.Client()

    def _clean(self, html: str) -> str:
        try:
            from bs4 import BeautifulSoup  # 可选依赖，缺失时优雅降级
        except ImportError as exc:
            raise DataSourceUnavailableError(
                "bs4 未安装，无法解析页面。请 `pip install beautifulsoup4`。"
            ) from exc
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:  # noqa: BLE001 - lxml 解析器失败时回退标准库 html.parser
            soup = BeautifulSoup(html, "html.parser")
        for tag in soup(_SKIP_TAGS):
            tag.decompose()
        text = soup.get_text(separator="\n")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return "\n".join(lines)[:20000]