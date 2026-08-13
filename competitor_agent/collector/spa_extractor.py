"""SpaExtractor — SPA 页面抓取（可选 Playwright 支持）

竞品官网常为单页应用（React/Vue），requests 只能拿到空壳 HTML。
本模块用 Playwright 渲染 JS 后再抽取文本。Playwright 是可选依赖
（`pip install -e .[spa]`），未安装时 graceful 降级为不可用，
由 SourceSelector 降级链继续尝试其他源。

设计：
- 惰性导入 playwright，未装时 is_available()==False。
- 提供 `fetch_text` 钩子供测试注入，无需真实浏览器。
"""
from __future__ import annotations

import logging
from typing import Callable

from competitor_agent.domain_types.enums import ObservationStatus
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation, SourceEvidence
from competitor_agent.interfaces.context import SourceContext
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError

logger = logging.getLogger("competitor_agent.collector.spa_extractor")

_SKIP_TAGS = {"script", "style", "noscript", "svg", "head", "nav", "footer"}

# url → html 的注入式渲染钩子（测试用；生产用 Playwright）
RenderPageFn = Callable[[str], str]


class SpaExtractor:
    """基于 Playwright 的 SPA 渲染抓取器（渐进增强）。"""

    def __init__(
        self,
        wait_until: str = "networkidle",
        wait_ms: int = 2000,
        max_text_chars: int = 20000,
        render_page: RenderPageFn | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._wait_until = wait_until
        self._wait_ms = wait_ms
        self._max_text_chars = max_text_chars
        self._render_page = render_page
        self._timeout = timeout

    @property
    def source_name(self) -> str:
        return "spa_extractor"

    def is_available(self) -> bool:
        # 注入钩子（测试）或真实 playwright 可用 → 可用
        if self._render_page is not None:
            return True
        try:
            import playwright  # type: ignore[import]  # noqa: F401

            return True
        except ImportError:  # pragma: no cover - 取决于运行环境是否装 playwright
            return False

    def fetch(self, gap: InfoGap, context: SourceContext) -> Observation:
        url = str(context.kwargs.get("url", ""))
        if not url:
            raise DataSourceUnavailableError(f"缺少 SPA 抓取 URL: gap={gap.field}")

        html = self._render(url)
        text = self._clean(html)
        if not text:
            raise DataSourceUnavailableError(f"SPA 渲染后无内容: {url}")

        evidence = SourceEvidence(
            source_name=self.source_name,
            url=url,
            content_hash=SourceEvidence.compute_hash(text),
            trust_level=0.9,
        )
        status = ObservationStatus.OK if len(text) > 50 else ObservationStatus.DEGRADED
        return Observation(
            gap_field=gap.field,
            source=self.source_name,
            raw_text=text,
            evidence=evidence,
            status=status,
        )

    def _render(self, url: str) -> str:
        """真实渲染：注入钩子 → 回退到 Playwright。"""
        if self._render_page is not None:
            return self._render_page(url)
        return self._render_with_playwright(url)

    def _render_with_playwright(self, url: str) -> str:  # pragma: no cover - 需真实浏览器
        try:
            from playwright.sync_api import sync_playwright  # type: ignore[import]
        except ImportError as exc:
            raise DataSourceUnavailableError(
                "Playwright 未安装，无法渲染 SPA 页面。请 `pip install -e .[spa]` 后执行 `playwright install`。"
            ) from exc

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until=self._wait_until, timeout=self._timeout * 1000)
                page.wait_for_timeout(self._wait_ms)
                return page.content()  # type: ignore[no-any-return]
            finally:
                browser.close()

    def _clean(self, html: str) -> str:
        try:
            from bs4 import BeautifulSoup  # 可选依赖（与 Playwright 同机制），缺失时优雅降级
        except ImportError as exc:
            raise DataSourceUnavailableError(
                "bs4 未安装，无法解析 SPA 渲染内容。请 `pip install beautifulsoup4`。"
            ) from exc
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:  # lxml 解析器缺失时回退标准库 html.parser
            soup = BeautifulSoup(html, "html.parser")
        for tag in soup(_SKIP_TAGS):
            tag.decompose()
        text = soup.get_text(separator="\n")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return "\n".join(lines)[: self._max_text_chars]