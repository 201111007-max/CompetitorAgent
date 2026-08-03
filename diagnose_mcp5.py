"""诊断: 检查 create_call_wrapper 如何处理 bound method"""
import asyncio
import sys
import os
import inspect

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def diagnose():
    from dota_helper.mcp_server.server import mcp
    from mcp.types import ListToolsRequest
    from mcp.server.lowlevel.func_inspection import create_call_wrapper

    # 检查 FastMCP.list_tools 方法
    print("=" * 60)
    print("检查 FastMCP.list_tools")
    print("=" * 60)
    bound_method = mcp.list_tools
    print(f"bound_method: {bound_method}")
    print(f"type: {type(bound_method)}")
    print(f"__self__: {bound_method.__self__}")
    print(f"__func__: {bound_method.__func__}")
    
    sig = inspect.signature(bound_method)
    print(f"signature: {sig}")
    print(f"parameters: {list(sig.parameters.keys())}")
    
    type_hints = {}
    try:
        type_hints = inspect.get_annotations(bound_method)
        print(f"annotations: {type_hints}")
    except Exception as e:
        print(f"annotations error: {e}")
    
    # 检查 create_call_wrapper 的行为
    print()
    print("=" * 60)
    print("检查 create_call_wrapper")
    print("=" * 60)
    wrapper = create_call_wrapper(bound_method, ListToolsRequest)
    print(f"wrapper: {wrapper}")
    
    # 调用 wrapper
    result = await wrapper(ListToolsRequest(method="tools/list", params=None))
    print(f"wrapper result type: {type(result).__name__}")
    print(f"wrapper result length: {len(result)}")
    if result:
        print(f"first tool: {result[0].name}")

    # 现在模拟低层 handler 的代码
    print()
    print("=" * 60)
    print("模拟低层 handler")
    print("=" * 60)
    from mcp.types import ListToolsResult, ServerResult
    
    # 这是低层 handler 中的代码
    handler_result = await wrapper(ListToolsRequest(method="tools/list", params=None))
    print(f"handler_result type: {type(handler_result).__name__}")
    
    if isinstance(handler_result, ListToolsResult):
        print("handler_result is ListToolsResult")
        print(f"tools: {len(handler_result.tools)}")
    else:
        print("handler_result is NOT ListToolsResult, it's a list")
        print(f"length: {len(handler_result)}")
        
        # 模拟 else 分支
        from mcp.server.lowlevel.server import validate_and_warn_tool_name
        tool_cache = {}
        for tool in handler_result:
            validate_and_warn_tool_name(tool.name)
            tool_cache[tool.name] = tool
        result_obj = ServerResult(ListToolsResult(tools=handler_result))
        print(f"result_obj type: {type(result_obj).__name__}")
        print(f"result_obj.root.tools: {len(result_obj.root.tools)}")

if __name__ == "__main__":
    asyncio.run(diagnose())
