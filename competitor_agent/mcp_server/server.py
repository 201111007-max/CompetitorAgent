"""MCP Server — 对外暴露竞品分析能力

启动：
    pip install -e ".[mcp]"
    python -m competitor_agent.mcp_server.server

MCP Client 可通过 stdio 或 SSE 调用工具。
"""
from __future__ import annotations

import logging

from competitor_agent.mcp_server.tools import (
    analyze_competitor,
    analyze_pricing,
    github_commits,
    github_releases,
    github_stars,
    run_benchmark,
    web_extract,
    web_search,
)

logger = logging.getLogger("competitor_agent.mcp_server")

try:
    from mcp.server.fastmcp import FastMCP

    _HAS_MCP = True
except ImportError:
    _HAS_MCP = False
    FastMCP = None  # type: ignore[assignment,misc]


def _require_mcp() -> None:
    if not _HAS_MCP:
        raise ImportError(
            "MCP 依赖未安装，请执行: pip install -e '.[mcp]'"
        )


def create_server() -> object:
    """创建并配置 FastMCP 服务器实例"""
    _require_mcp()
    mcp = FastMCP("Competitor Intelligence Agent")

    # ── Web 工具 ──────────────────────────────────────────────────────

    @mcp.tool()
    def web_extract_tool(url: str, selector: str = "") -> str:
        """采集指定 URL 的网页内容

        Args:
            url: 目标网页 URL
            selector: CSS 选择器（可选，留空则采集全文）
        Returns:
            网页文本内容
        """
        return web_extract(url, selector)

    @mcp.tool()
    def web_search_tool(query: str, max_results: int = 5) -> str:
        """搜索竞品相关信息

        Args:
            query: 搜索关键词
            max_results: 最大结果数（默认 5）
        Returns:
            搜索结果摘要
        """
        return web_search(query, max_results)

    # ── 定价工具 ──────────────────────────────────────────────────────

    @mcp.tool()
    def analyze_pricing_tool(competitor: str, url: str = "") -> str:
        """分析竞品定价信息

        Args:
            competitor: 竞品名称
            url: 定价页面 URL（可选，自动查找）
        Returns:
            定价分析结果
        """
        return analyze_pricing(competitor, url)

    # ── GitHub 工具 ───────────────────────────────────────────────────

    @mcp.tool()
    def github_stars_tool(repo: str) -> str:
        """查询 GitHub 仓库的 star 数

        Args:
            repo: 仓库名，格式 owner/repo（如 "anthropics/claude-code"）
        Returns:
            Star 数及仓库基本信息
        """
        return github_stars(repo)

    @mcp.tool()
    def github_releases_tool(repo: str, limit: int = 5) -> str:
        """查询 GitHub 仓库的发布版本

        Args:
            repo: 仓库名，格式 owner/repo
            limit: 返回版本数（默认 5）
        Returns:
            版本发布列表
        """
        return github_releases(repo, limit)

    @mcp.tool()
    def github_commits_tool(repo: str, days: int = 30) -> str:
        """查询 GitHub 仓库近期提交

        Args:
            repo: 仓库名，格式 owner/repo
            days: 查询天数范围（默认 30）
        Returns:
            近期提交列表
        """
        return github_commits(repo, days)

    # ── 评测工具 ──────────────────────────────────────────────────────

    @mcp.tool()
    def run_benchmark_tool() -> str:
        """运行竞品分析评测基准

        Returns:
            评测结果（准确率/幻觉率/工具选择准确率）
        """
        return run_benchmark()

    # ── 综合工具 ──────────────────────────────────────────────────────

    @mcp.tool()
    def analyze_competitor_tool(task: str) -> str:
        """综合分析一个竞品（采集→分析→报告全流程）

        Args:
            task: 分析任务，如 "分析 Cursor"
        Returns:
            Markdown 格式的分析报告
        """
        return analyze_competitor(task)

    return mcp


def run_stdio() -> None:
    """通过 stdio 传输运行 MCP Server"""
    _require_mcp()
    mcp = create_server()
    logger.info("MCP Server 启动（stdio 模式）")
    mcp.run(transport="stdio")  # type: ignore[attr-defined]


def run_sse(host: str = "127.0.0.1", port: int = 8001) -> None:
    """通过 SSE 传输运行 MCP Server"""
    _require_mcp()
    mcp = create_server()
    logger.info("MCP Server 启动（SSE 模式，%s:%d）", host, port)
    mcp.run(transport="sse", host=host, port=port)  # type: ignore[attr-defined]


def main() -> None:
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="竞品分析 Agent MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="传输方式")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="SSE 模式监听地址")
    parser.add_argument("--port", type=int, default=8001, help="SSE 模式监听端口")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if args.transport == "sse":
        run_sse(host=args.host, port=args.port)
    else:
        run_stdio()


if __name__ == "__main__":
    main()
