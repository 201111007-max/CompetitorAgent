"""MCP Server — 对外暴露竞品分析能力

启动：
    pip install -e ".[mcp]"
    python -m competitor_agent.mcp_server.server

MCP Client 可通过 stdio 或 SSE 调用工具。
"""
from __future__ import annotations

import logging

from competitor_agent.mcp_server.tools import TOOL_SPECS, TOOLS

logger = logging.getLogger("competitor_agent.mcp_server")

try:
    from mcp.server.fastmcp import FastMCP

    _HAS_MCP = True
except ImportError:
    _HAS_MCP = False
    FastMCP = None


def _require_mcp() -> None:
    if not _HAS_MCP:
        raise ImportError(
            "MCP 依赖未安装，请执行: pip install -e '.[mcp]'"
        )


def create_server() -> object:
    """创建并配置 FastMCP 服务器实例

    工具由 ``mcp_server.tools.TOOL_SPECS`` 同源生成（设计文档 40）——
    描述/schema 只维护工具注册表一份，这里不再手写重复文案。
    """
    _require_mcp()
    mcp = FastMCP("Competitor Intelligence Agent")
    for name, spec in TOOL_SPECS.items():
        mcp.tool(name=name, description=spec.description)(TOOLS[name])
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

    # 设计文档 74 §3.1/E2：启动强制应用用户级 env（忽略 shell 注入的 DEEPSEEK_API_KEY / OPENAI_BASE_URL）
    from competitor_agent.config.user_env import apply_user_level_environment

    apply_user_level_environment()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if args.transport == "sse":
        run_sse(host=args.host, port=args.port)
    else:
        run_stdio()


if __name__ == "__main__":
    main()
