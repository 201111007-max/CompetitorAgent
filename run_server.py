"""MCP Server 独立入口脚本

避免 python -m 导致的循环导入问题。
先导入 server 模块（注册到 sys.modules），再启动。
"""
import asyncio
import sys
import os

# 确保项目根目录在 sys.path 中
_project_root = os.path.abspath(os.path.dirname(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 先导入 server 模块（注册到 sys.modules 为 dota_helper.mcp_server.server）
from dota_helper.mcp_server.server import mcp, startup, shutdown


async def main() -> None:
    await startup()
    try:
        await mcp.run_stdio_async()
    finally:
        await shutdown()


if __name__ == "__main__":
    asyncio.run(main())
