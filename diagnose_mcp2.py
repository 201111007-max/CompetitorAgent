"""深入诊断 MCP list_tools 序列化问题"""
import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def diagnose():
    from dota_helper.mcp_server.server import mcp
    from mcp.types import Tool as MCPTool, ListToolsResult, ServerResult
    from mcp.server.fastmcp.tools.base import Tool as FastMCPTool

    # 1. 检查 FastMCP.list_tools() 返回的 MCPTool 对象
    print("=" * 60)
    print("诊断 1: FastMCP.list_tools() 返回的 MCPTool 对象")
    print("=" * 60)
    tools = await mcp.list_tools()
    print(f"返回 {len(tools)} 个工具")
    if tools:
        t = tools[0]
        print(f"第一个工具: name={t.name}")
        print(f"  type: {type(t)}")
        print(f"  model_dump: {json.dumps(t.model_dump(mode='json', exclude_none=True), indent=2)[:500]}")
        print(f"  model_dump(by_alias=True): {json.dumps(t.model_dump(by_alias=True, mode='json', exclude_none=True), indent=2)[:500]}")

    # 2. 检查 ServerResult 序列化
    print()
    print("=" * 60)
    print("诊断 2: ServerResult 序列化")
    print("=" * 60)
    result = ListToolsResult(tools=tools)
    server_result = ServerResult(result)
    dumped = server_result.model_dump(by_alias=True, mode="json", exclude_none=True)
    print(f"ServerResult model_dump keys: {list(dumped.keys())}")
    if "result" in dumped:
        print(f"result keys: {list(dumped['result'].keys())}")
        if "tools" in dumped["result"]:
            print(f"tools count: {len(dumped['result']['tools'])}")
            if dumped["result"]["tools"]:
                print(f"first tool keys: {list(dumped['result']['tools'][0].keys())}")
        else:
            print("❌ 'tools' key NOT in result!")
            print(f"result content: {json.dumps(dumped['result'], indent=2)[:500]}")
    else:
        print("❌ 'result' key NOT in ServerResult dump!")
        print(f"dumped: {json.dumps(dumped, indent=2)[:500]}")

    # 3. 检查低层 handler 的返回
    print()
    print("=" * 60)
    print("诊断 3: 低层 handler 返回")
    print("=" * 60)
    from mcp.types import ListToolsRequest
    mcp_server = mcp._mcp_server
    handler = mcp_server.request_handlers[ListToolsRequest]
    req = ListToolsRequest(method="tools/list", params=None)
    handler_result = await handler(req)
    print(f"handler 返回类型: {type(handler_result).__name__}")
    handler_dumped = handler_result.model_dump(by_alias=True, mode="json", exclude_none=True)
    print(f"handler result model_dump keys: {list(handler_dumped.keys())}")
    if "result" in handler_dumped:
        if "tools" in handler_dumped["result"]:
            print(f"tools count: {len(handler_dumped['result']['tools'])}")
        else:
            print("❌ 'tools' key NOT in handler result!")
            print(f"result content: {json.dumps(handler_dumped['result'], indent=2)[:500]}")
    else:
        print(f"handler_dumped: {json.dumps(handler_dumped, indent=2)[:500]}")

    # 4. 模拟完整的 JSON-RPC 消息
    print()
    print("=" * 60)
    print("诊断 4: 模拟 JSON-RPC 响应消息")
    print("=" * 60)
    from mcp.shared.message import SessionMessage
    from mcp.types import JSONRPCResponse, JSONRPCMessage
    jsonrpc_response = JSONRPCResponse(
        jsonrpc="2.0",
        id=1,
        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
    )
    print(f"JSONRPCResponse result keys: {list(jsonrpc_response.result.keys())}")
    if "tools" in jsonrpc_response.result:
        print(f"tools count: {len(jsonrpc_response.result['tools'])}")
    else:
        print("❌ 'tools' key NOT in JSONRPCResponse result!")
        print(f"result: {json.dumps(jsonrpc_response.result, indent=2)[:500]}")

    # 5. 检查客户端反序列化
    print()
    print("=" * 60)
    print("诊断 5: 客户端反序列化 ListToolsResult")
    print("=" * 60)
    from mcp.types import ListToolsResult as ClientListToolsResult
    # 模拟客户端收到的 JSON
    json_data = result.model_dump(by_alias=True, mode="json", exclude_none=True)
    print(f"JSON data keys: {list(json_data.keys())}")
    if "tools" in json_data:
        print(f"tools count in JSON: {len(json_data['tools'])}")
        # 尝试反序列化
        try:
            parsed = ClientListToolsResult.model_validate(json_data)
            print(f"反序列化后 tools 数量: {len(parsed.tools)}")
        except Exception as e:
            print(f"❌ 反序列化失败: {e}")
    else:
        print("❌ 'tools' key NOT in JSON data!")
        print(f"JSON data: {json.dumps(json_data, indent=2)[:500]}")

if __name__ == "__main__":
    asyncio.run(diagnose())
