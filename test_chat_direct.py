"""直接测试 /api/chat 端点，捕获完整输出"""
import asyncio
import json
import sys
import os
import socket

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test():
    # 启动服务子进程
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-m", "uvicorn",
        "dota_helper.web_app:app",
        "--host", "127.0.0.1",
        "--port", "8765",
        "--log-level", "debug",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={
            **os.environ,
            "PYTHONPATH": os.path.dirname(os.path.abspath(__file__)),
            "NO_PROXY": "localhost,127.0.0.1",
        },
    )

    # 读取 stderr 中的日志
    async def read_stderr():
        try:
            while True:
                line = await asyncio.wait_for(proc.stderr.readline(), timeout=30)
                if not line:
                    break
                text = line.decode('utf-8', errors='replace').rstrip()
                if text:
                    print(f"[STDERR] {text}", flush=True)
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            print(f"[STDERR] Error: {e}", flush=True)

    stderr_task = asyncio.create_task(read_stderr())

    # 等待服务启动
    await asyncio.sleep(8)

    print("\n" + "="*60, flush=True)
    print("Sending POST /api/chat", flush=True)
    print("="*60, flush=True)

    # 用 socket 直接发送 HTTP 请求
    reader, writer = await asyncio.open_connection("127.0.0.1", 8765)

    body = json.dumps({"message": "复盘比赛 8909780728"})
    request = (
        f"POST /api/chat HTTP/1.1\r\n"
        f"Host: 127.0.0.1:8765\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
        f"{body}"
    )
    writer.write(request.encode())
    await writer.drain()

    # 读取响应
    response_data = b""
    try:
        while True:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=60)
            if not chunk:
                break
            response_data += chunk
            # 打印实时数据
            print(f"[RECV] {chunk.decode('utf-8', errors='replace')}", flush=True)
    except asyncio.TimeoutError:
        print("[TIMEOUT] No more data received", flush=True)
    except Exception as e:
        print(f"[ERROR] {e}", flush=True)

    writer.close()
    print(f"\n[SUMMARY] Total received: {len(response_data)} bytes", flush=True)

    # 终止服务
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        proc.kill()
    stderr_task.cancel()
    print("[DONE]", flush=True)

if __name__ == "__main__":
    asyncio.run(test())
