"""启动 MCP Server 子进程并捕获所有输出"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test():
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m", "dota_helper.mcp_server.server",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.abspath(__file__))},
    )
    
    # 读取所有输出（带超时）
    try:
        stdout_data, stderr_data = await asyncio.wait_for(
            proc.communicate(), timeout=10
        )
    except asyncio.TimeoutError:
        proc.terminate()
        stdout_data, stderr_data = await proc.communicate()
    
    print("=== STDOUT ===")
    print(stdout_data.decode('utf-8', errors='replace'))
    print("=== STDERR ===")
    print(stderr_data.decode('utf-8', errors='replace'))

if __name__ == "__main__":
    asyncio.run(test())
