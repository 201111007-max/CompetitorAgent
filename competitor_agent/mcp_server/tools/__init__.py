"""MCP Server 工具 — 竞品采集与分析工具

工具按领域分组：
- web: 网页采集
- pricing: 定价分析
- github: GitHub 信息
- benchmark: 评测
- review: 综合审查

TOOLS / TOOL_SPECS（设计文档 40）：MCP↔ReAct 唯一工具定义源。
ReAct（agent/tool_registry.build_react_dispatcher）与 MCP Server（server.create_server）
同源生成工具——描述 / schema（设计文档 38 契约）只维护这里一份，杜绝两处重复。
"""
from __future__ import annotations

from typing import Any, Callable

from competitor_agent.agent.tool_dispatcher import ToolSpec
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

TOOLS: dict[str, Callable[..., str]] = {
    "web_extract": web_extract,
    "web_search": web_search,
    "analyze_pricing": analyze_pricing,
    "github_stars": github_stars,
    "github_releases": github_releases,
    "github_commits": github_commits,
    "run_benchmark": run_benchmark,
    "analyze_competitor": analyze_competitor,
}


def _schema(required: dict[str, str], optional: dict[str, str] | None = None) -> dict[str, Any]:
    """由 {参数: JSON 类型} 构建 params_schema（设计文档 38 JSON Schema 子集）"""
    props = {
        **{k: {"type": t} for k, t in required.items()},
        **{k: {"type": t} for k, t in (optional or {}).items()},
    }
    return {"type": "object", "required": list(required), "properties": props}


TOOL_SPECS: dict[str, ToolSpec] = {
    "web_extract": ToolSpec(
        "web_extract", web_extract,
        description="采集指定 URL 的网页文本（URL 过安全守卫，防 SSRF）",
        params_schema=_schema({"url": "string"}, {"selector": "string"}),
    ),
    "web_search": ToolSpec(
        "web_search", web_search,
        description="搜索竞品相关信息（需接入搜索引擎 API）",
        params_schema=_schema({"query": "string"}, {"max_results": "integer"}),
    ),
    "analyze_pricing": ToolSpec(
        "analyze_pricing", analyze_pricing,
        description="分析竞品定价信息（可指定定价页 URL）",
        params_schema=_schema({"competitor": "string"}, {"url": "string"}),
    ),
    "github_stars": ToolSpec(
        "github_stars", github_stars,
        description="查询 GitHub 仓库 star/fork/语言等基本信息",
        params_schema=_schema({"repo": "string"}),
    ),
    "github_releases": ToolSpec(
        "github_releases", github_releases,
        description="查询 GitHub 仓库最近版本发布",
        params_schema=_schema({"repo": "string"}, {"limit": "integer"}),
    ),
    "github_commits": ToolSpec(
        "github_commits", github_commits,
        description="查询 GitHub 仓库近期提交",
        params_schema=_schema({"repo": "string"}, {"days": "integer"}),
    ),
    "run_benchmark": ToolSpec(
        "run_benchmark", run_benchmark,
        description="运行竞品分析评测基准（字段准确率/幻觉率/工具选择准确率）",
        params_schema={"type": "object", "properties": {}},
    ),
    "analyze_competitor": ToolSpec(
        "analyze_competitor", analyze_competitor,
        description="综合分析一个竞品（采集→分析→报告全流程）",
        params_schema=_schema({"task": "string"}),
    ),
}

__all__ = [
    "TOOLS",
    "TOOL_SPECS",
    "analyze_competitor",
    "analyze_pricing",
    "github_commits",
    "github_releases",
    "github_stars",
    "run_benchmark",
    "web_extract",
    "web_search",
]
