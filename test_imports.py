"""测试在子进程中导入 server 模块"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 模拟子进程环境
print("Importing dota_helper.mcp_server.server...")
try:
    from dota_helper.mcp_server.server import mcp
    import asyncio
    
    async def check():
        tools = await mcp.list_tools()
        print(f"Tools registered: {len(tools)}")
        if tools:
            for t in tools[:3]:
                print(f"  - {t.name}")
        else:
            print("WARNING: No tools registered!")
    
    asyncio.run(check())
except Exception as e:
    import traceback
    traceback.print_exc()
