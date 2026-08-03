"""诊断 stdio 传输层 - 使用 SessionMessage 发送"""
import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def diagnose():
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.shared.message import SessionMessage
    from mcp.types import (
        JSONRPCMessage, JSONRPCResponse, JSONRPCRequest, JSONRPCNotification,
        InitializeRequestParams,
    )

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "dota_helper.mcp_server.server"],
    )

    print("Connecting via stdio...")
    async with stdio_client(server_params) as (read_stream, write_stream):
        print("stdio_client connected")
        
        # 使用 SessionMessage 发送 initialize
        init_params = InitializeRequestParams(
            protocolVersion="2024-11-05",
            capabilities={},
            clientInfo={"name": "test-client", "version": "1.0.0"},
        )
        init_request = JSONRPCRequest(
            jsonrpc="2.0",
            id=1,
            method="initialize",
            params=init_params.model_dump(by_alias=True, mode="json", exclude_none=True),
        )
        msg = SessionMessage(message=JSONRPCMessage(init_request))
        await write_stream.send(msg)
        print("Sent initialize request")
        
        # 读取响应
        response_msg = await read_stream.receive()
        print(f"Response type: {type(response_msg).__name__}")
        if isinstance(response_msg, SessionMessage):
            root = response_msg.message.root
            print(f"Root type: {type(root).__name__}")
            if isinstance(root, JSONRPCResponse):
                print(f"Init response result keys: {list(root.result.keys())}")
                caps = root.result.get("capabilities", {})
                print(f"Capabilities: {json.dumps(caps, indent=2)[:200]}")
            elif hasattr(root, 'result'):
                print(f"result: {json.dumps(root.result, indent=2)[:200]}")
        else:
            print(f"Raw response: {str(response_msg)[:200]}")
        
        # 发送 initialized notification
        init_notif = JSONRPCNotification(
            jsonrpc="2.0",
            method="notifications/initialized",
        )
        msg = SessionMessage(message=JSONRPCMessage(init_notif))
        await write_stream.send(msg)
        print("Sent initialized notification")
        
        # 发送 list_tools 请求
        list_req = JSONRPCRequest(
            jsonrpc="2.0",
            id=2,
            method="tools/list",
        )
        msg = SessionMessage(message=JSONRPCMessage(list_req))
        await write_stream.send(msg)
        print("Sent list_tools request")
        
        # 读取 list_tools 响应
        response_msg = await read_stream.receive()
        print(f"\nResponse type: {type(response_msg).__name__}")
        if isinstance(response_msg, SessionMessage):
            root = response_msg.message.root
            print(f"Root type: {type(root).__name__}")
            if isinstance(root, JSONRPCResponse):
                result = root.result
                print(f"result keys: {list(result.keys())}")
                if "tools" in result:
                    print(f"tools count: {len(result['tools'])}")
                    if result["tools"]:
                        print(f"first tool: {result['tools'][0]['name']}")
                    else:
                        print("❌ tools is EMPTY array!")
                        print(f"Full result: {json.dumps(result, indent=2)[:500]}")
                else:
                    print(f"❌ NO 'tools' key!")
                    print(f"Full result: {json.dumps(result, indent=2)[:500]}")
            elif hasattr(root, 'error'):
                print(f"Error: {json.dumps(root.error, indent=2)}")
        else:
            print(f"Raw: {str(response_msg)[:500]}")

if __name__ == "__main__":
    asyncio.run(diagnose())
