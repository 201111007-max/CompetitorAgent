"""MCP Server 工具 — 竞品采集与分析工具

工具按领域分组：
- web: 网页采集
- pricing: 定价分析
- github: GitHub 信息
- benchmark: 评测
- review: 综合审查
"""
from __future__ import annotations

from competitor_agent.mcp_server.tools.benchmark_tools import (
    run_benchmark,
)
from competitor_agent.mcp_server.tools.github_tools import (
    github_commits,
    github_releases,
    github_stars,
)
from competitor_agent.mcp_server.tools.pricing_tools import (
    analyze_pricing,
)
from competitor_agent.mcp_server.tools.review_tools import (
    analyze_competitor,
)
from competitor_agent.mcp_server.tools.web_tools import (
    web_extract,
    web_search,
)

__all__ = [
    "analyze_competitor",
    "analyze_pricing",
    "github_commits",
    "github_releases",
    "github_stars",
    "run_benchmark",
    "web_extract",
    "web_search",
]
