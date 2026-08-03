"""诊断 MCP list_tools 返回空列表的问题"""
import asyncio
import sys
import os

# 确保能找到 dota_helper 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def diagnose():
    print("=" * 60)
    print("诊断 1: 直接调用 FastMCP.list_tools()")
    print("=" * 60)
    from dota_helper.mcp_server.server import mcp
    tools = await mcp.list_tools()
    print(f"  FastMCP.list_tools() 返回 {len(tools)} 个工具")
    if tools:
        for t in tools[:3]:
            print(f"    - {t.name}: {t.description[:50]}")
        print(f"    ... 共 {len(tools)} 个")
    else:
        print("  ❌ 返回空列表！")

    print()
    print("=" * 60)
    print("诊断 2: 检查 ToolManager._tools")
    print("=" * 60)
    tm = mcp._tool_manager
    print(f"  ToolManager._tools 类型: {type(tm._tools)}")
    print(f"  ToolManager._tools 长度: {len(tm._tools)}")
    if tm._tools:
        for name in list(tm._tools.keys())[:3]:
            print(f"    - {name}")
        print(f"    ... 共 {len(tm._tools)} 个")
    else:
        print("  ❌ ToolManager._tools 为空！")

    print()
    print("=" * 60)
    print("诊断 3: 检查 MCPServer.request_handlers")
    print("=" * 60)
    from mcp.types import ListToolsRequest
    mcp_server = mcp._mcp_server
    handler = mcp_server.request_handlers.get(ListToolsRequest)
    print(f"  ListToolsRequest handler 已注册: {handler is not None}")
    if handler:
        print(f"  handler 类型: {type(handler).__name__}")

    print()
    print("=" * 60)
    print("诊断 4: 通过 handler 直接调用")
    print("=" * 60)
    if handler:
        req = ListToolsRequest(method="tools/list", params=None)
        result = await handler(req)
        print(f"  handler 返回类型: {type(result).__name__}")
        if hasattr(result, 'root'):
            print(f"  result.root 类型: {type(result.root).__name__}")
            if hasattr(result.root, 'tools'):
                print(f"  result.root.tools 长度: {len(result.root.tools)}")
                if result.root.tools:
                    for t in result.root.tools[:3]:
                        print(f"    - {t.name}")
                else:
                    print("  ❌ result.root.tools 为空！")
            else:
                print(f"  result.root 属性: {dir(result.root)}")
        else:
            print(f"  result 属性: {dir(result)}")

    print()
    print("=" * 60)
    print("诊断 5: 检查 MCPServer.create_initialization_options()")
    print("=" * 60)
    from mcp.server.models import InitializationOptions
    opts = mcp_server.create_initialization_options()
    print(f"  server_name: {opts.server_name}")
    print(f"  capabilities: {opts.capabilities}")
    if opts.capabilities:
        print(f"  tools capability: {opts.capabilities.tools}")

    print()
    print("=" * 60)
    print("诊断 6: 检查 create_call_wrapper 行为")
    print("=" * 60)
    from mcp.server.lowlevel.func_inspection import create_call_wrapper
    wrapper = create_call_wrapper(mcp.list_tools, ListToolsRequest)
    wrapper_result = await wrapper(ListToolsRequest(method="tools/list", params=None))
    print(f"  wrapper 返回类型: {type(wrapper_result).__name__}")
    print(f"  wrapper 返回长度: {len(wrapper_result)}")
    if wrapper_result:
        for t in wrapper_result[:3]:
            print(f"    - {t.name}")

    print()
    print("=" * 60)
    print("诊断 7: 通过 stdio 通信测试")
    print("=" * 60)
    try:
        from mcp.client.stdio import StdioServerParameters, stdio_client
        from mcp.client.session import ClientSession

        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "dota_helper.mcp_server.server"],
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                init_result = await session.initialize()
                print(f"  服务器: {init_result.serverInfo.name} v{init_result.serverInfo.version}")
                caps = init_result.capabilities
                print(f"  capabilities: {caps}")
                if caps:
                    print(f"  tools capability: {caps.tools}")

                result = await session.list_tools()
                print(f"  session.list_tools() 返回 {len(result.tools)} 个工具")
                if result.tools:
                    for t in result.tools[:3]:
                        print(f"    - {t.name}")
                else:
                    print("  ❌ 通过 stdio 返回空列表！")
    except Exception as e:
        print(f"  ❌ stdio 通信失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(diagnose())
