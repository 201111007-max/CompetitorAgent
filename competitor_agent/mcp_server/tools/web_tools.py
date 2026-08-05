"""MCP Server — 网页采集工具"""
from __future__ import annotations

import logging

logger = logging.getLogger("competitor_agent.mcp_server.tools.web_tools")


def web_extract(url: str, selector: str = "") -> str:
    """采集指定 URL 的网页内容"""
    try:
        import httpx
        from bs4 import BeautifulSoup

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = httpx.get(url, headers=headers, timeout=15.0, follow_redirects=True)
        resp.raise_for_status()

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
        max_chars = 8000
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...（截断）"

        return text or f"⚠ 未从 {url} 提取到内容"
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
