"""ToolDispatcher MCP Client 集成测试

测试 ToolDispatcher 与 MCPClient/NoOpMCPClient 的交互。
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from dota_helper.agent.tool_dispatcher import ToolDispatcher
from dota_helper.mcp_client.client import MCPClient, NoOpMCPClient
from dota_helper.mcp_client.types import ToolInfo, MCPConnectionError


class TestToolDispatcherWithNoOp:
    """ToolDispatcher + NoOpMCPClient 测试"""

    def test_create_with_noop(self) -> None:
        """测试使用 NoOpMCPClient 创建分发器"""
        noop = NoOpMCPClient(reason="test")
        dispatcher = ToolDispatcher(mcp_client=noop)
        assert dispatcher.is_connected is False
        assert dispatcher.tool_count == 0

    def test_tool_descriptions_noop(self) -> None:
        """测试 NoOp 模式下的工具描述"""
        noop = NoOpMCPClient(reason="test")
        dispatcher = ToolDispatcher(mcp_client=noop)
        desc = dispatcher.get_tool_descriptions()
        assert "暂无可用工具" in desc

    def test_dispatch_noop_not_connected(self) -> None:
        """测试 NoOp 未连接时调用工具抛出 RuntimeError"""
        noop = NoOpMCPClient(reason="test")
        dispatcher = ToolDispatcher(mcp_client=noop)
        # 先加载工具到 name set
        dispatcher._tool_name_set.add("get_heroes")
        with pytest.raises(RuntimeError):
            asyncio.run(dispatcher.dispatch("get_heroes", {}))

    def test_connect_noop(self) -> None:
        """测试 NoOp 的 connect 不出错"""
        noop = NoOpMCPClient(reason="test")
        dispatcher = ToolDispatcher(mcp_client=noop)
        asyncio.run(dispatcher.connect())
        # NoOp 连接后仍然是未连接状态
        assert dispatcher.is_connected is False

    def test_disconnect_noop(self) -> None:
        """测试 NoOp 的 disconnect 不出错"""
        noop = NoOpMCPClient(reason="test")
        dispatcher = ToolDispatcher(mcp_client=noop)
        asyncio.run(dispatcher.disconnect())


class TestToolDispatcherWithMCPClient:
    """ToolDispatcher + MCPClient 测试（不连接真实 Server）"""

    def test_create_with_mcp_client(self) -> None:
        """测试使用 MCPClient 创建分发器"""
        client = MCPClient()
        dispatcher = ToolDispatcher(mcp_client=client)
        assert dispatcher.is_connected is False
        assert dispatcher.tool_count == 0

    def test_dispatch_not_connected(self) -> None:
        """测试未连接时调用工具抛出 RuntimeError"""
        client = MCPClient()
        dispatcher = ToolDispatcher(mcp_client=client)
        dispatcher._tool_name_set.add("get_heroes")
        with pytest.raises(RuntimeError):
            asyncio.run(dispatcher.dispatch("get_heroes", {}))

    def test_dispatch_invalid_tool(self) -> None:
        """测试调用不存在的工具抛出 ValueError"""
        client = MCPClient()
        dispatcher = ToolDispatcher(mcp_client=client)
        with pytest.raises(ValueError):
            asyncio.run(dispatcher.dispatch("nonexistent_tool", {}))


class TestToolDispatcherWithTools:
    """ToolDispatcher 工具加载测试"""

    def test_load_tools_from_cache(self) -> None:
        """测试从 ToolInfo 列表加载工具"""
        noop = NoOpMCPClient(reason="test")
        dispatcher = ToolDispatcher(mcp_client=noop)

        tools = [
            ToolInfo(name="get_heroes", description="获取英雄列表", parameters={}),
            ToolInfo(name="get_match_details", description="获取比赛详情", parameters={}),
            ToolInfo(name="get_player_info", description="获取玩家信息", parameters={}),
        ]
        dispatcher._load_tools_from_cache(tools)

        assert dispatcher.tool_count == 3
        assert dispatcher.validate_tool("get_heroes") is True
        assert dispatcher.validate_tool("get_match_details") is True
        assert dispatcher.validate_tool("unknown") is False

    def test_tool_descriptions_format(self) -> None:
        """测试工具描述格式化"""
        noop = NoOpMCPClient(reason="test")
        dispatcher = ToolDispatcher(mcp_client=noop)

        tools = [
            ToolInfo(
                name="get_heroes",
                description="获取英雄列表",
                parameters={},
            ),
        ]
        dispatcher._load_tools_from_cache(tools)

        desc = dispatcher.get_tool_descriptions()
        assert "get_heroes" in desc
        assert "获取英雄列表" in desc

    def test_update_tools_compatible(self) -> None:
        """测试 update_tools 旧接口兼容"""
        noop = NoOpMCPClient(reason="test")
        dispatcher = ToolDispatcher(mcp_client=noop)

        dispatcher.update_tools([
            {"name": "tool_a", "description": "desc_a", "schema": {}},
            {"name": "tool_b", "description": "desc_b", "schema": {}},
        ])
        assert dispatcher.tool_count == 2
        assert dispatcher.validate_tool("tool_a") is True


class TestToolDispatcherWithoutClient:
    """ToolDispatcher 无 MCP Client 测试"""

    def test_create_without_client(self) -> None:
        """测试不传入 MCP Client 创建分发器"""
        dispatcher = ToolDispatcher()
        assert dispatcher.is_connected is False
        assert dispatcher.tool_count == 0

    def test_connect_without_client(self) -> None:
        """测试无 Client 时 connect 不出错"""
        dispatcher = ToolDispatcher()
        asyncio.run(dispatcher.connect())

    def test_dispatch_without_client(self) -> None:
        """测试无 Client 时调用工具抛出 RuntimeError"""
        dispatcher = ToolDispatcher()
        dispatcher._tool_name_set.add("get_heroes")
        with pytest.raises(RuntimeError):
            asyncio.run(dispatcher.dispatch("get_heroes", {}))
