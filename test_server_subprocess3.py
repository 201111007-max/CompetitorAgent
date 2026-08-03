"""启动 MCP Server 子进程，实时捕获输出"""
import asyncio
import sys
import os
import json

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
    
    async def read_stream(stream, label):
        try:
            while True:
                line = await asyncio.wait_for(stream.readline(), timeout=5)
                if not line:
                    break
                text = line.decode('utf-8', errors='replace').rstrip()
                if text:
                    print(f"[{label}] {text}", flush=True)
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            print(f"[{label}] Error: {e}", flush=True)
    
    stderr_task = asyncio.create_task(read_stream(proc.stderr, "STDERR"))
    stdout_task = asyncio.create_task(read_stream(proc.stdout, "STDOUT"))
    
    # 等待服务器启动
    await asyncio.sleep(5)
    
    # 发送 initialize 请求
    init = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"}
        }
    }
    proc.stdin.write((json.dumps(init) + "\n").encode())
    await proc.stdin.drain()
    print("[CLIENT] Sent initialize", flush=True)
    await asyncio.sleep(2)
    
    # 发送 initialized
    notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    proc.stdin.write((json.dumps(notif) + "\n").encode())
    await proc.stdin.drain()
    print("[CLIENT] Sent initialized", flush=True)
    await asyncio.sleep(1)
    
    # 发送 list_tools
    list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    proc.stdin.write((json.dumps(list_req) + "\n").encode())
    await proc.stdin.drain()
    print("[CLIENT] Sent list_tools", flush=True)
    await asyncio.sleep(3)
    
    # 终止
    proc.terminate()
    stderr_task.cancel()
    stdout_task.cancel()
    print("[CLIENT] Done", flush=True)

if __name__ == "__main__":
    asyncio.run(test())
