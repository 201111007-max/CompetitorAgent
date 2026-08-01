"""本地工具注册机制单元测试"""
import pytest

from dota_helper.agent.tool_registry import ToolRegistry


class TestToolRegistry:
    """测试 ToolRegistry 的注册和调用"""

    def setup_method(self) -> None:
        self.registry = ToolRegistry()

    def test_register_sync_tool(self) -> None:
        """注册同步工具"""
        def my_tool(args: dict) -> str:
            return f"result: {args.get('key', 'none')}"

        name = self.registry.register(
            "my_tool",
            handler=my_tool,
            description="A test tool",
            schema={
                "properties": {
                    "key": {"type": "string", "description": "A key"}
                },
                "required": ["key"],
            },
        )
        assert name == "my_tool"
        assert self.registry.count == 1
        assert self.registry.has_tool("my_tool")

    @pytest.mark.asyncio
    async def test_register_async_tool(self) -> None:
        """注册异步工具"""
        async def my_async_tool(args: dict) -> str:
            return f"async: {args.get('key', 'none')}"

        self.registry.register("async_tool", handler=my_async_tool, description="Async tool")
        assert self.registry.has_tool("async_tool")

        result = await self.registry.call_tool("async_tool", {"key": "value"})
        assert result == "async: value"

    @pytest.mark.asyncio
    async def test_call_sync_tool(self) -> None:
        """调用同步工具"""
        def my_tool(args: dict) -> str:
            return f"result: {args.get('key', 'none')}"

        self.registry.register("my_tool", handler=my_tool)
        result = await self.registry.call_tool("my_tool", {"key": "hello"})
        assert result == "result: hello"

    @pytest.mark.asyncio
    async def test_call_nonexistent_tool_raises(self) -> None:
        """调用不存在的工具抛出 ValueError"""
        with pytest.raises(ValueError, match="不存在"):
            await self.registry.call_tool("nonexistent", {})

    def test_register_duplicate_raises(self) -> None:
        """重复注册同名工具抛出 ValueError"""
        def my_tool(args: dict) -> str:
            return "ok"

        self.registry.register("my_tool", handler=my_tool)
        with pytest.raises(ValueError, match="已注册"):
            self.registry.register("my_tool", handler=my_tool)

    def test_unregister(self) -> None:
        """卸载工具"""
        def my_tool(args: dict) -> str:
            return "ok"

        self.registry.register("my_tool", handler=my_tool)
        assert self.registry.count == 1

        result = self.registry.unregister("my_tool")
        assert result is True
        assert self.registry.count == 0
        assert not self.registry.has_tool("my_tool")

    def test_unregister_nonexistent_returns_false(self) -> None:
        """卸载不存在的工具返回 False"""
        result = self.registry.unregister("nonexistent")
        assert result is False

    def test_get_tool(self) -> None:
        """获取工具定义"""
        def my_tool(args: dict) -> str:
            return "ok"

        self.registry.register("my_tool", handler=my_tool, description="desc")
        tool = self.registry.get_tool("my_tool")
        assert tool is not None
        assert tool.name == "my_tool"
        assert tool.description == "desc"
        assert tool.is_async is False

    def test_get_tool_nonexistent(self) -> None:
        """获取不存在的工具返回 None"""
        tool = self.registry.get_tool("nonexistent")
        assert tool is None

    def test_tool_names(self) -> None:
        """获取所有工具名称"""
        def t1(args: dict) -> str:
            return "1"

        def t2(args: dict) -> str:
            return "2"

        self.registry.register("tool1", handler=t1)
        self.registry.register("tool2", handler=t2)
        names = self.registry.tool_names
        assert "tool1" in names
        assert "tool2" in names
        assert len(names) == 2

    def test_get_descriptions_empty(self) -> None:
        """空注册表返回空字符串"""
        desc = self.registry.get_descriptions()
        assert desc == ""

    def test_get_descriptions_with_schema(self) -> None:
        """获取工具描述（含 schema）"""
        def my_tool(args: dict) -> str:
            return "ok"

        self.registry.register(
            "my_tool",
            handler=my_tool,
            description="A test tool",
            schema={
                "properties": {
                    "name": {"type": "string", "description": "The name"},
                    "count": {"type": "integer", "description": "The count"},
                },
                "required": ["name"],
            },
        )
        desc = self.registry.get_descriptions()
        assert "my_tool" in desc
        assert "A test tool" in desc
        assert "name" in desc
        assert "count" in desc
        assert "必填" in desc

    def test_clear(self) -> None:
        """清空注册表"""
        def my_tool(args: dict) -> str:
            return "ok"

        self.registry.register("my_tool", handler=my_tool)
        assert self.registry.count == 1

        self.registry.clear()
        assert self.registry.count == 0

    @pytest.mark.asyncio
    async def test_tool_handler_error_propagates(self) -> None:
        """工具处理函数异常向上传播"""
        def broken_tool(args: dict) -> str:
            raise RuntimeError("something went wrong")

        self.registry.register("broken", handler=broken_tool)
        with pytest.raises(RuntimeError, match="something went wrong"):
            await self.registry.call_tool("broken", {})
