"""MCP Server — 对外暴露竞品分析能力"""
from competitor_agent.mcp_server.server import create_server, run_sse, run_stdio

__all__ = ["create_server", "run_sse", "run_stdio"]
