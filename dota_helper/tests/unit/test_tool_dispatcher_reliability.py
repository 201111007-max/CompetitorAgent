"""ToolDispatcher 可靠性特性测试 — 熔断器 + 重试逻辑"""
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from dota_helper.agent.circuit_breaker import CircuitBreakerRegistry
from dota_helper.agent.tool_dispatcher import ToolDispatcher
from dota_helper.mcp_client.types import MCPConnectionError, ToolInfo


# ── Mock MCP Client ──

class MockMCPClient:
    """模拟 MCPClient，可控地抛出异常"""

    def __init__(self) -> None:
        self._connected = True
        self._call_behavior: Dict[str, Any] = {}  # tool_name → {"raise": Exception | None, "result": str}
        self._call_count: Dict[str, int] = {}
        self.tools: List[ToolInfo] = [
            ToolInfo(name="get_match_details", description="Get match details"),
            ToolInfo(name="get_match_items", description="Get match items"),
            ToolInfo(name="generate_review_report", description="Generate review"),
        ]

    @property
    def is_connected(self) -> bool:
        return self._connected

    def set_behavior(self, tool_name: str, *, raise_exc: Optional[Exception] = None, result: str = "ok") -> None:
        """设置工具调用的行为"""
        self._call_behavior[tool_name] = {"raise": raise_exc, "result": result}

    def set_behavior_sequence(self, tool_name: str, behaviors: List[Dict[str, Any]]) -> None:
        """设置工具调用的序列行为（第 N 次调用抛出什么）"""
        self._call_behavior[tool_name] = {"sequence": behaviors, "_call_index": 0}

    async def call_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        self._call_count[tool_name] = self._call_count.get(tool_name, 0) + 1
        behavior = self._call_behavior.get(tool_name, {})
        if "sequence" in behavior:
            idx = behavior.get("_call_index", 0)
            if idx < len(behavior["sequence"]):
                item = behavior["sequence"][idx]
                behavior["_call_index"] = idx + 1
                if item.get("raise"):
                    raise item["raise"]
                return item.get("result", "ok")
            return "ok"
        if behavior.get("raise"):
            raise behavior["raise"]
        return behavior.get("result", "ok")

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def list_tools(self) -> List[ToolInfo]:
        return self.tools


class TestToolDispatcherCircuitBreaker:
    """测试 ToolDispatcher 的熔断器集成"""

    @pytest.fixture
    def mock_client(self) -> MockMCPClient:
        return MockMCPClient()

    @pytest.fixture
    def registry(self) -> CircuitBreakerRegistry:
        return CircuitBreakerRegistry(default_failure_threshold=2, default_recovery_timeout=60)

    @pytest.fixture
    def dispatcher(self, mock_client: MockMCPClient, registry: CircuitBreakerRegistry) -> ToolDispatcher:
        return ToolDispatcher(mcp_client=mock_client, circuit_breaker_registry=registry)

    @pytest.mark.asyncio
    async def test_successful_call_resets_breaker(self, dispatcher: ToolDispatcher, mock_client: MockMCPClient) -> None:
        """成功调用后熔断器重置"""
        mock_client.set_behavior("get_match_details", result="match data")
        result = await dispatcher.dispatch("get_match_details", {"match_id": 123})
        assert result == "match data"

    @pytest.mark.asyncio
    async def test_failure_triggers_breaker(self, dispatcher: ToolDispatcher, mock_client: MockMCPClient) -> None:
        """连续失败触发熔断"""
        mock_client.set_behavior("get_match_details", raise_exc=ValueError("bad arg"))
        with pytest.raises(ValueError):
            await dispatcher.dispatch("get_match_details", {})
        # 第 1 次失败，未熔断
        assert dispatcher._circuit_breaker.allow_request("get_match_details") is True
        with pytest.raises(ValueError):
            await dispatcher.dispatch("get_match_details", {})
        # 第 2 次失败，达到阈值 → 熔断
        assert dispatcher._circuit_breaker.allow_request("get_match_details") is False

    @pytest.mark.asyncio
    async def test_breaker_blocks_request(self, dispatcher: ToolDispatcher, mock_client: MockMCPClient) -> None:
        """熔断后 dispatch 直接抛出 MCPConnectionError"""
        mock_client.set_behavior("get_match_details", raise_exc=ValueError("bad arg"))
        # 触发熔断（2 次失败）
        for _ in range(2):
            with pytest.raises(ValueError):
                await dispatcher.dispatch("get_match_details", {})
        # 第 3 次调用被熔断阻止
        with pytest.raises(MCPConnectionError, match="已被熔断"):
            await dispatcher.dispatch("get_match_details", {})

    @pytest.mark.asyncio
    async def test_breaker_only_affects_failing_tool(self, dispatcher: ToolDispatcher, mock_client: MockMCPClient) -> None:
        """熔断只影响失败的工具，其他工具正常"""
        mock_client.set_behavior("get_match_details", raise_exc=ValueError("bad arg"))
        mock_client.set_behavior("get_match_items", result="items data")
        # 触发 get_match_details 熔断
        for _ in range(2):
            with pytest.raises(ValueError):
                await dispatcher.dispatch("get_match_details", {})
        # get_match_items 不受影响
        result = await dispatcher.dispatch("get_match_items", {"match_id": 123})
        assert result == "items data"

    @pytest.mark.asyncio
    async def test_success_after_failure_resets_breaker(self, dispatcher: ToolDispatcher, mock_client: MockMCPClient) -> None:
        """失败后成功调用重置熔断器"""
        mock_client.set_behavior("get_match_details", raise_exc=ValueError("bad arg"))
        with pytest.raises(ValueError):
            await dispatcher.dispatch("get_match_details", {})
        # 改为成功
        mock_client.set_behavior("get_match_details", result="ok")
        result = await dispatcher.dispatch("get_match_details", {})
        assert result == "ok"
        # 熔断器已重置
        assert dispatcher._circuit_breaker.allow_request("get_match_details") is True


class TestToolDispatcherRetry:
    """测试 ToolDispatcher 的自动重试逻辑"""

    @pytest.fixture
    def mock_client(self) -> MockMCPClient:
        return MockMCPClient()

    @pytest.fixture
    def dispatcher(self, mock_client: MockMCPClient) -> ToolDispatcher:
        return ToolDispatcher(mcp_client=mock_client)

    @pytest.mark.asyncio
    async def test_retry_on_timeout(self, dispatcher: ToolDispatcher, mock_client: MockMCPClient) -> None:
        """MCP 超时自动重试，成功后返回结果"""
        mock_client.set_behavior_sequence("get_match_details", [
            {"raise": MCPConnectionError(MCPConnectionError.TIMEOUT, "timeout")},
            {"result": "match data after retry"},
        ])
        result = await dispatcher.dispatch("get_match_details", {"match_id": 123})
        assert result == "match data after retry"
        assert mock_client._call_count["get_match_details"] == 2

    @pytest.mark.asyncio
    async def test_retry_on_connection_lost(self, dispatcher: ToolDispatcher, mock_client: MockMCPClient) -> None:
        """MCP 连接丢失自动重试"""
        mock_client.set_behavior_sequence("get_match_details", [
            {"raise": MCPConnectionError(MCPConnectionError.CONNECTION_LOST, "reset")},
            {"result": "ok after reconnect"},
        ])
        result = await dispatcher.dispatch("get_match_details", {})
        assert result == "ok after reconnect"

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises(self, dispatcher: ToolDispatcher, mock_client: MockMCPClient) -> None:
        """重试耗尽后抛出最后一次异常"""
        mock_client.set_behavior("get_match_details",
                                  raise_exc=MCPConnectionError(MCPConnectionError.TIMEOUT, "always timeout"))
        with pytest.raises(MCPConnectionError, match="always timeout"):
            await dispatcher.dispatch("get_match_details", {})
        # 重试 1 次 + 原始 1 次 = 2 次调用
        assert mock_client._call_count["get_match_details"] == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_value_error(self, dispatcher: ToolDispatcher, mock_client: MockMCPClient) -> None:
        """ValueError 不重试"""
        mock_client.set_behavior("get_match_details", raise_exc=ValueError("bad arg"))
        with pytest.raises(ValueError):
            await dispatcher.dispatch("get_match_details", {})
        # 只调用 1 次
        assert mock_client._call_count["get_match_details"] == 1

    @pytest.mark.asyncio
    async def test_no_retry_on_startup_failed(self, dispatcher: ToolDispatcher, mock_client: MockMCPClient) -> None:
        """MCP 启动失败不重试"""
        mock_client.set_behavior("get_match_details",
                                  raise_exc=MCPConnectionError(MCPConnectionError.STARTUP_FAILED, "crashed"))
        with pytest.raises(MCPConnectionError):
            await dispatcher.dispatch("get_match_details", {})
        assert mock_client._call_count["get_match_details"] == 1

    @pytest.mark.asyncio
    async def test_retry_then_breaker(self, dispatcher: ToolDispatcher, mock_client: MockMCPClient) -> None:
        """重试耗尽后熔断器记录失败"""
        registry = dispatcher._circuit_breaker
        mock_client.set_behavior("get_match_details",
                                  raise_exc=MCPConnectionError(MCPConnectionError.TIMEOUT, "timeout"))
        with pytest.raises(MCPConnectionError):
            await dispatcher.dispatch("get_match_details", {})
        # 熔断器记录了 1 次失败
        assert registry.get("get_match_details").failure_count == 1
