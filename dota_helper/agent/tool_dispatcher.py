"""MCP 工具分发器 — 将 Agent 的 Action 映射到 53 个 MCP 工具

ToolDispatcher 是 Agent 与 MCP Server 之间的桥梁：
- dispatch(): 将 LLM 决策的工具调用转发到 MCP Server
- get_tool_descriptions(): 获取所有工具描述注入系统提示词
- validate_tool(): 校验工具名是否可用
- connect() / disconnect(): 管理 MCP Client 连接生命周期

> 耦合说明：ToolDispatcher 依赖 MCP Client 连接 MCP Server，
> 详见 MCP Client 集成设计文档。

可靠性特性：
- 熔断器：连续失败 3 次后自动暂停调用 30 秒
- 重试：MCP 超时和连接丢失自动重试（最多 2 次，指数退避）
"""
import asyncio
from typing import Any, Dict, List, Optional, Union

from dota_helper.agent.circuit_breaker import CircuitBreakerRegistry
from dota_helper.agent.tool_registry import ToolRegistry
from dota_helper.mcp_client.client import MCPClient, NoOpMCPClient
from dota_helper.mcp_client.types import ToolInfo, MCPConnectionError
from dota_helper.observability.logger import get_logger

logger = get_logger("agent.tool_dispatcher")

# 重试参数
_MAX_RETRY_ATTEMPTS = 2
_RETRY_BASE_DELAY = 1.0  # 秒


class ToolDispatcher:
    """MCP 工具分发器，将 Agent 的 Action 映射到真实 MCP 工具

    通过 MCP Client 与 MCP Server 通信，支持 53 个 Dota 2 分析工具的调用。
    同时管理 MCP Client 的连接生命周期。

    Args:
        mcp_client: MCPClient 或 NoOpMCPClient 实例
    """

    def __init__(
        self,
        mcp_client: Optional[Union[MCPClient, NoOpMCPClient]] = None,
        circuit_breaker_registry: Optional[CircuitBreakerRegistry] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ) -> None:
        """初始化工具分发器

        Args:
            mcp_client: MCP Client 实例（MCPClient 或降级模式 NoOpMCPClient）
            circuit_breaker_registry: 熔断器注册表（可选，默认创建新实例）
            tool_registry: 本地工具注册表（可选）
        """
        self._mcp_client: Optional[Union[MCPClient, NoOpMCPClient]] = mcp_client
        self._available_tools: List[Dict[str, Any]] = []
        self._tool_name_set: set = set()
        self._circuit_breaker = circuit_breaker_registry or CircuitBreakerRegistry()
        self._tool_registry = tool_registry or ToolRegistry()

        # 如果 MCP Client 已连接且有工具缓存，自动加载
        if mcp_client is not None and hasattr(mcp_client, "tools") and mcp_client.tools:
            self._load_tools_from_cache(mcp_client.tools)

        logger.info(
            "工具分发器初始化: mcp_client=%s, tools=%d",
            "connected" if (mcp_client and mcp_client.is_connected) else "none",
            len(self._available_tools),
        )

    async def connect(self) -> None:
        """连接 MCP Server 并加载工具列表

        通过 MCP Client spawn MCP Server 子进程、建立 stdio 会话，
        然后获取 53 个工具的描述并更新内部列表。

        Raises:
            MCPConnectionError: MCP Server 启动或连接失败
        """
        if self._mcp_client is None:
            logger.warning("无 MCP Client 实例，无法连接")
            return

        if self._mcp_client.is_connected:
            logger.debug("MCP Client 已连接，跳过")
            return

        logger.info("正在通过 MCP Client 连接 MCP Server...")
        await self._mcp_client.connect()

        # 连接成功后，加载工具列表
        if self._mcp_client.is_connected:
            tools = await self._mcp_client.list_tools()
            self._load_tools_from_cache(tools)
            logger.info("MCP Server 连接成功，已加载 %d 个工具", len(self._available_tools))

    async def disconnect(self) -> None:
        """断开 MCP Server 连接

        关闭 ClientSession 并终止 MCP Server 子进程。
        """
        if self._mcp_client is not None:
            await self._mcp_client.disconnect()
            self._available_tools = []
            self._tool_name_set = set()
            logger.info("MCP Server 连接已断开")

    async def dispatch(
        self,
        tool_name: str,
        args: Dict[str, Any],
    ) -> str:
        """分发工具调用到 MCP Server（含熔断检查和自动重试）

        Args:
            tool_name: 工具名称（如 'get_match_details'）
            args: 工具参数字典

        Returns:
            str: 工具执行结果文本

        Raises:
            ValueError: 工具名不在可用列表中
            MCPConnectionError: MCP 连接错误（重试耗尽后抛出）
            RuntimeError: MCP Client 未连接
        """
        # 优先检查本地工具
        if self._tool_registry.has_tool(tool_name):
            logger.info("分发本地工具调用: tool=%s, args=%s", tool_name, args)
            return await self._tool_registry.call_tool(tool_name, args)

        if not self.validate_tool(tool_name):
            logger.warning("工具不存在: %s", tool_name)
            raise ValueError(f"工具 '{tool_name}' 不在可用工具列表中")

        if self._mcp_client is None:
            logger.error("MCP Client 未初始化，无法调用工具: %s", tool_name)
            raise RuntimeError("MCP Client 未初始化，请先创建 ToolDispatcher 并传入 MCPClient")

        if not self._mcp_client.is_connected:
            logger.error("MCP Client 未连接，无法调用工具: %s", tool_name)
            raise RuntimeError("MCP Client 未连接，请先调用 connect()")

        # 熔断检查
        if not self._circuit_breaker.allow_request(tool_name):
            raise MCPConnectionError(
                MCPConnectionError.CONNECTION_LOST,
                f"工具 '{tool_name}' 已被熔断，暂时无法调用",
            )

        logger.info("分发 MCP 工具调用: tool=%s, args=%s", tool_name, args)

        # 带重试的调用
        last_error: Optional[Exception] = None
        for attempt in range(1, _MAX_RETRY_ATTEMPTS + 1):
            try:
                result = await self._mcp_client.call_tool(tool_name, args)
                logger.debug(
                    "工具调用成功: tool=%s, result_len=%d",
                    tool_name, len(str(result)),
                )
                self._circuit_breaker.on_success(tool_name)
                return str(result)

            except MCPConnectionError as e:
                last_error = e
                # 仅对超时和连接丢失重试
                if e.reason in (MCPConnectionError.TIMEOUT, MCPConnectionError.CONNECTION_LOST):
                    if attempt < _MAX_RETRY_ATTEMPTS:
                        delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                        logger.warning(
                            "工具调用重试 %d/%d: tool=%s, delay=%.1fs",
                            attempt, _MAX_RETRY_ATTEMPTS, tool_name, delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                # 其他 MCP 错误不重试
                break

            except Exception as e:
                last_error = e
                logger.error("工具调用失败: tool=%s, error=%s", tool_name, str(e))
                break

        # 所有重试耗尽
        self._circuit_breaker.on_failure(tool_name)
        raise last_error  # type: ignore[misc]

    def get_tool_descriptions(self) -> str:
        """获取所有工具的格式化描述（注入系统提示词）

        将可用工具列表格式化为 LLM 可理解的自然语言描述，
        包含工具名、功能说明和参数 schema。
        优先包含本地注册工具，再包含 MCP 工具。

        Returns:
            str: 格式化的工具描述文本
        """
        descriptions = []

        # 本地工具
        local_desc = self._tool_registry.get_descriptions()
        if local_desc:
            descriptions.append("【本地工具】")
            descriptions.append(local_desc)

        # MCP 工具
        if self._available_tools:
            descriptions.append("【MCP 工具】")
            for tool in self._available_tools:
                name = tool.get("name", "unknown")
                desc = tool.get("description", "无描述")
                schema = tool.get("schema", {})

                tool_desc = f"- {name}: {desc}"
                if schema:
                    params = schema.get("properties", {})
                    if params:
                        param_strs = []
                        for param_name, param_info in params.items():
                            param_type = param_info.get("type", "any")
                            param_desc = param_info.get("description", "")
                            param_strs.append(f"  - {param_name} ({param_type}): {param_desc}")
                        tool_desc += "\n" + "\n".join(param_strs)

                descriptions.append(tool_desc)

        if not descriptions:
            return "（暂无可用工具）"

        return "\n".join(descriptions)

    def validate_tool(self, tool_name: str) -> bool:
        """校验工具名是否存在于可用工具列表（含本地工具）

        Args:
            tool_name: 工具名称

        Returns:
            bool: 工具是否可用
        """
        return tool_name in self._tool_name_set or self._tool_registry.has_tool(tool_name)

    @property
    def tool_count(self) -> int:
        """可用工具数量

        Returns:
            int: 工具数量
        """
        return len(self._available_tools)

    @property
    def is_connected(self) -> bool:
        """MCP Client 连接状态

        Returns:
            bool: 是否已连接
        """
        return self._mcp_client is not None and self._mcp_client.is_connected

    def _load_tools_from_cache(self, tools: List[ToolInfo]) -> None:
        """从 ToolInfo 列表加载工具到内部可用列表

        Args:
            tools: ToolInfo 列表（来自 MCP Client 的工具缓存）
        """
        self._available_tools = [tool.to_dict() for tool in tools]
        self._tool_name_set = {tool.name for tool in tools}
        logger.debug("工具列表已加载: count=%d", len(tools))

    def update_tools(self, tools: List[Dict[str, Any]]) -> None:
        """更新可用工具列表（兼容旧接口）

        Args:
            tools: 新的工具列表
        """
        self._available_tools = tools
        self._tool_name_set = {tool.get("name", "") for tool in tools}
        logger.info("工具列表更新: count=%d", len(tools))
