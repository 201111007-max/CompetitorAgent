"""诊断 ServerResult 序列化/反序列化"""
import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def diagnose():
    from dota_helper.mcp_server.server import mcp
    from mcp.types import Tool as MCPTool, ListToolsResult, ServerResult, JSONRPCResponse

    tools = await mcp.list_tools()
    print(f"FastMCP.list_tools() 返回 {len(tools)} 个工具")

    # 模拟 handler 中的代码
    list_result = ListToolsResult(tools=tools)
    print(f"ListToolsResult.tools 长度: {len(list_result.tools)}")

    server_result = ServerResult(list_result)
    print(f"ServerResult 类型: {type(server_result).__name__}")
    print(f"ServerResult.root 类型: {type(server_result.root).__name__}")

    # 序列化
    dumped = server_result.model_dump(by_alias=True, mode="json", exclude_none=True)
    print(f"model_dump 类型: {type(dumped).__name__}")
    print(f"model_dump 值: {json.dumps(dumped, indent=2)[:200]}")

    # 构建 JSONRPCResponse
    jsonrpc_response = JSONRPCResponse(
        jsonrpc="2.0",
        id=1,
        result=dumped,
    )
    print(f"\nJSONRPCResponse.result 类型: {type(jsonrpc_response.result).__name__}")
    print(f"JSONRPCResponse.result keys: {list(jsonrpc_response.result.keys())}")
    if "tools" in jsonrpc_response.result:
        print(f"tools count: {len(jsonrpc_response.result['tools'])}")
    else:
        print("❌ NO tools key!")

    # 模拟客户端反序列化
    print(f"\n客户端反序列化:")
    client_parsed = ListToolsResult.model_validate(jsonrpc_response.result)
    print(f"ListToolsResult.model_validate 返回 {len(client_parsed.tools)} 个工具")

    # 关键测试: 检查 ServerResult 的 model_dump 是否返回了正确的结构
    # 问题: ServerResult 是 RootModel, model_dump 返回 root 值
    # 但 JSONRPCResponse.result 期望的是 dict[str, Any]
    # 如果 ServerResult 的 root 是 ListToolsResult, model_dump 返回的是 ListToolsResult 的 dict
    # 这应该是正确的...

    # 但让我们检查一下 ServerResult 的 model_dump 是否真的返回了 dict
    print(f"\nServerResult model_dump 返回类型: {type(dumped)}")
    print(f"ServerResult model_dump 内容: {json.dumps(dumped, indent=2)[:300]}")

    # 检查是否有其他字段被排除
    print(f"\n检查 exclude_none 的影响:")
    dumped_all = server_result.model_dump(by_alias=True, mode="json")
    print(f"model_dump (without exclude_none) keys: {list(dumped_all.keys())}")
    if isinstance(dumped_all, dict):
        print(f"  type: dict, keys: {list(dumped_all.keys())}")
    else:
        print(f"  type: {type(dumped_all)}")

    # 检查 ServerResult 的 model_dump(mode='python')
    dumped_python = server_result.model_dump(mode='python')
    print(f"\nmodel_dump(mode='python') 类型: {type(dumped_python).__name__}")
    if isinstance(dumped_python, dict):
        print(f"  keys: {list(dumped_python.keys())}")
    else:
        print(f"  值: {type(dumped_python)}")

if __name__ == "__main__":
    asyncio.run(diagnose())
