"""MCP Server — 网页采集工具"""
from __future__ import annotations

import logging
import urllib.parse

import httpx

from competitor_agent.config.loader import load_config
from competitor_agent.core.url_guard import URLError, guard_http_url

logger = logging.getLogger("competitor_agent.mcp_server.tools.web_tools")

_MAX_REDIRECTS = 5


def web_extract(url: str, selector: str = "") -> str:
    """采集指定 URL 的网页内容（URL 过安全守卫，重定向逐跳重校验，防 SSRF）"""
    collector = load_config().collector
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # URL 守卫（设计文档 41）先于任何抓取执行：私网/保留地址拒绝；重定向逐跳重校验
    try:
        current = guard_http_url(url) if collector.block_private_urls else url
    except URLError as e:
        return f"⚠ URL 被安全守卫拦截: {e}"

    try:
        resp = None
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
        resp.raise_for_status()

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return "⚠ 采集异常: 缺少依赖 bs4（解析网页需要）"

        soup = BeautifulSoup(resp.text, "lxml")
        if selector:
            elements = soup.select(selector)
            text = "\n".join(el.get_text(strip=True) for el in elements)
        else:
            # 移除 script/style
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)

        # 截断过长内容
        max_chars = collector.max_content_chars
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...（截断）"

        return text or f"⚠ 未从 {url} 提取到内容"
    except URLError as e:
        return f"⚠ URL 被安全守卫拦截: {e}"
    except httpx.HTTPStatusError as e:
        return f"⚠ HTTP {e.response.status_code}: {url}"
    except httpx.RequestError as e:
        return f"⚠ 请求失败: {e}"
    except Exception as e:  # noqa: BLE001
        logger.warning("web_extract(%s) 异常: %s", url, e)
        return f"⚠ 采集异常: {e}"


def web_search(query: str, max_results: int = 5) -> str:
    """搜索竞品相关信息（模拟搜索，实际可接入搜索引擎 API）"""
    # 简化实现：返回提示信息
    return (
        f"搜索功能需要接入搜索引擎 API（如 SerpAPI / Bing Search）。\n"
        f"查询: {query}\n"
        f"建议: 使用 web_extract 直接采集已知竞品官网。"
    )
