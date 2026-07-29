"""MCP Client 模块 — 连接 MCP Server 并调用工具

通过 stdio 与 MCP Server 子进程通信，提供工具发现和调用能力。
当 MCP SDK 不可用时，自动降级为无工具模式。
"""
from dota_helper.mcp_client.client import MCPClient
from dota_helper.mcp_client.types import ToolInfo, MCPConnectionError

__all__ = ["MCPClient", "ToolInfo", "MCPConnectionError"]
