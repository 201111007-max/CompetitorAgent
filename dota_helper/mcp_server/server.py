"""FastMCP Server 入口 — 统一 Dota 2 工具层

自动收集所有工具模块注册的 @mcp.tool() 装饰器，
提供单个 MCP Server 供 Agent 的 MCP Client 连接。
"""

import os
from typing import Optional

from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# 创建 FastMCP 实例
mcp = FastMCP("Dota2 Helper Agent")

# 读取 .env（用于 SerpApi、OpenDota API Key 等第三方配置）
_ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
load_dotenv(_ENV_PATH, override=False)

# 初始化共享异步 OpenDota 客户端
from dota_helper.mcp_server.helpers.opendota import AsyncOpenDotaClient

_opendota_client: Optional[AsyncOpenDotaClient] = None


def _ensure_opendota_client() -> AsyncOpenDotaClient:
    """确保 OpenDota 客户端已初始化

    Returns:
        AsyncOpenDotaClient: 已初始化的客户端实例
    """
    global _opendota_client
    if _opendota_client is None:
        api_key = os.getenv("OPENDOTA_API_KEY", "").strip() or None
        _opendota_client = AsyncOpenDotaClient(api_key=api_key)
        AsyncOpenDotaClient.set_instance(_opendota_client)
    return _opendota_client


# 导入所有工具模块（注册 @mcp.tool() 装饰器）
# 这些导入必须在 mcp 对象创建之后
from dota_helper.mcp_server.tools import (  # noqa: F401
    match_tools,
    hero_tools,
    player_tools,
    team_tools,
    ward_tools,
    search_tools,
    stats_tools,
    review_tools,
)


def create_server() -> FastMCP:
    """创建 MCP Server 实例（用于测试和自定义）

    Returns:
        FastMCP: MCP Server 实例
    """
    _ensure_opendota_client()
    return mcp


async def startup() -> None:
    """MCP Server 启动时初始化资源"""
    client = _ensure_opendota_client()
    # 预加载英雄列表（首次 API 调用，后续走缓存）
    try:
        await client.get_heroes()
    except Exception:
        pass


async def shutdown() -> None:
    """MCP Server 关闭时释放资源"""
    global _opendota_client
    if _opendota_client is not None:
        await _opendota_client.close()
        _opendota_client = None


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        await startup()
        try:
            await mcp.run_stdio_async()
        finally:
            await shutdown()

    asyncio.run(_main())
