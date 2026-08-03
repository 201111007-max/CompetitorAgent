"""启动 MCP Server 子进程并测试 list_tools"""
import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test():
    # 启动子进程
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m", "dota_helper.mcp_server.server",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.abspath(__file__))},
    )
    
    # 读取 stderr 中的 debug 输出
    async def read_stderr():
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            print(f"[STDERR] {line.decode('utf-8', errors='replace').strip()}", flush=True)
    
    stderr_task = asyncio.create_task(read_stderr())
    
    # 等待服务器启动
    await asyncio.sleep(3)
    
    # 发送 initialize 请求
    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"}
        }
    }
    proc.stdin.write((json.dumps(init_request) + "\n").encode('utf-8'))
    await proc.stdin.drain()
    print("[CLIENT] Sent initialize", flush=True)
    
    # 读取响应
    line = await asyncio.wait_for(proc.stdout.readline(), timeout=5)
    print(f"[CLIENT] Init response: {line.decode('utf-8').strip()[:200]}", flush=True)
    
    # 发送 initialized notification
    notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    proc.stdin.write((json.dumps(notif) + "\n").encode('utf-8'))
    await proc.stdin.drain()
    print("[CLIENT] Sent initialized", flush=True)
    
    # 发送 list_tools 请求
    list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    proc.stdin.write((json.dumps(list_req) + "\n").encode('utf-8'))
    await proc.stdin.drain()
    print("[CLIENT] Sent list_tools", flush=True)
    
    # 读取响应
    line = await asyncio.wait_for(proc.stdout.readline(), timeout=5)
    response = json.loads(line.decode('utf-8'))
    print(f"[CLIENT] List tools response: {json.dumps(response, indent=2)[:500]}", flush=True)
    
    # 终止进程
    proc.terminate()
    await asyncio.sleep(1)
    stderr_task.cancel()

if __name__ == "__main__":
    asyncio.run(test())
