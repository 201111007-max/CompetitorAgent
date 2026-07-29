"""MCP Client 单元测试

测试 MCPClient、NoOpMCPClient、ToolInfo、MCPConnectionError 的核心功能。
不依赖真实 MCP Server，使用 Mock 验证接口行为。
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from dota_helper.mcp_client.client import MCPClient, NoOpMCPClient
from dota_helper.mcp_client.types import ToolInfo, MCPConnectionError


class TestToolInfo:
    """ToolInfo 数据模型测试"""

    def test_create_tool_info(self) -> None:
        """测试创建 ToolInfo 实例"""
        tool = ToolInfo(
            name="get_match_details",
            description="获取比赛详情",
            parameters={"type": "object", "properties": {"match_id": {"type": "string"}}},
        )
        assert tool.name == "get_match_details"
        assert tool.description == "获取比赛详情"
        assert "match_id" in tool.parameters["properties"]

    def test_tool_info_to_dict(self) -> None:
        """测试 ToolInfo.to_dict() 转换"""
        tool = ToolInfo(
            name="get_heroes",
            description="获取英雄列表",
            parameters={"type": "object"},
        )
        d = tool.to_dict()
        assert d["name"] == "get_heroes"
        assert d["description"] == "获取英雄列表"
        assert d["schema"] == {"type": "object"}

    def test_tool_info_frozen(self) -> None:
        """测试 ToolInfo 是不可变的"""
        tool = ToolInfo(name="test", description="test", parameters={})
        with pytest.raises(AttributeError):
            tool.name = "changed"  # type: ignore

    def test_tool_info_default_parameters(self) -> None:
        """测试 ToolInfo 默认参数"""
        tool = ToolInfo(name="test", description="test")
        assert tool.parameters == {}


class TestMCPConnectionError:
    """MCPConnectionError 测试"""

    def test_startup_failed(self) -> None:
        """测试启动失败错误"""
        err = MCPConnectionError(MCPConnectionError.STARTUP_FAILED, "process not found")
        assert err.reason == "startup_failed"
        assert err.detail == "process not found"
        assert "startup_failed" in str(err)

    def test_connection_lost(self) -> None:
        """测试连接断开错误"""
        err = MCPConnectionError(MCPConnectionError.CONNECTION_LOST, "session closed")
        assert err.reason == "connection_lost"

    def test_timeout(self) -> None:
        """测试超时错误"""
        err = MCPConnectionError(MCPConnectionError.TIMEOUT, "30s exceeded")
        assert err.reason == "timeout"

    def test_sdk_unavailable(self) -> None:
        """测试 SDK 不可用错误"""
        err = MCPConnectionError(MCPConnectionError.SDK_UNAVAILABLE, "no mcp module")
        assert err.reason == "sdk_unavailable"


class TestMCPClient:
    """MCPClient 核心测试（不连接真实 Server）"""

    def test_create_default(self) -> None:
        """测试默认参数创建 MCPClient"""
        client = MCPClient()
        assert client.is_connected is False
        assert client.tools == []

    def test_create_custom(self) -> None:
        """测试自定义参数创建 MCPClient"""
        client = MCPClient(
            server_command="/usr/bin/python3",
            server_args=["-m", "my_server"],
            server_env={"API_KEY": "test"},
            call_timeout=60.0,
        )
        assert client.is_connected is False

    def test_call_tool_not_connected(self) -> None:
        """测试未连接时调用工具抛出错误"""
        client = MCPClient()
        with pytest.raises(MCPConnectionError) as exc_info:
            asyncio.run(client.call_tool("get_heroes", {}))
        assert exc_info.value.reason == MCPConnectionError.CONNECTION_LOST

    def test_list_tools_not_connected(self) -> None:
        """测试未连接时获取工具列表抛出错误"""
        client = MCPClient()
        with pytest.raises(MCPConnectionError) as exc_info:
            asyncio.run(client.list_tools())
        assert exc_info.value.reason == MCPConnectionError.CONNECTION_LOST

    def test_extract_text_content(self) -> None:
        """测试文本内容提取"""
        # 模拟 TextContent 对象
        mock_content = MagicMock()
        mock_content.text = "Hello World"
        result = MCPClient._extract_text_content([mock_content])
        assert result == "Hello World"

    def test_extract_text_content_multiple(self) -> None:
        """测试多个文本内容拼接"""
        items = [MagicMock(text="Line 1"), MagicMock(text="Line 2")]
        result = MCPClient._extract_text_content(items)
        assert "Line 1" in result
        assert "Line 2" in result

    def test_extract_text_content_empty(self) -> None:
        """测试空内容"""
        assert MCPClient._extract_text_content([]) == ""
        assert MCPClient._extract_text_content(None) == ""


class TestNoOpMCPClient:
    """NoOpMCPClient 降级模式测试"""

    def test_create(self) -> None:
        """测试创建 NoOpMCPClient"""
        client = NoOpMCPClient(reason="test")
        assert client.is_connected is False
        assert client.tools == []

    def test_connect_noop(self) -> None:
        """测试 NoOp 连接无操作"""
        client = NoOpMCPClient(reason="test")
        asyncio.run(client.connect())
        assert client.is_connected is False

    def test_disconnect_noop(self) -> None:
        """测试 NoOp 断开无操作"""
        client = NoOpMCPClient(reason="test")
        asyncio.run(client.disconnect())
        assert client.is_connected is False

    def test_call_tool_noop(self) -> None:
        """测试 NoOp 工具调用返回降级提示"""
        client = NoOpMCPClient(reason="SDK 不可用")
        result = asyncio.run(client.call_tool("get_heroes", {}))
        assert "⚠️" in result
        assert "MCP 工具不可用" in result
        assert "get_heroes" in result

    def test_list_tools_noop(self) -> None:
        """测试 NoOp 工具列表为空"""
        client = NoOpMCPClient(reason="test")
        result = asyncio.run(client.list_tools())
        assert result == []
