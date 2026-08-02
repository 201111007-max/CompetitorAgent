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
from dota_helper.agent.tool_guard import (
    AuditLog,
    ConfirmationRequired,
    RateLimitExceeded,
    SensitiveOperationGuard,
    ToolArgumentError,
    ToolArgumentValidator,
    ToolBlockedError,
    ToolRateLimiter,
)
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
        enable_tool_guard: 是否启用工具护栏（参数校验/敏感守卫/限速/审计，默认 True）
        tool_rate_limit: 是否启用速率限制（可独立关闭，默认 True）
        guard_config: 护栏自定义配置（可选），支持:
            - policies: Dict[str, str] 覆盖敏感操作默认策略
            - rate_limits: Dict[str, float] 覆盖默认限速配置
    """

    def __init__(
        self,
        mcp_client: Optional[Union[MCPClient, NoOpMCPClient]] = None,
        circuit_breaker_registry: Optional[CircuitBreakerRegistry] = None,
        tool_registry: Optional[ToolRegistry] = None,
        enable_tool_guard: bool = True,
        tool_rate_limit: bool = True,
        guard_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """初始化工具分发器

        Args:
            mcp_client: MCP Client 实例（MCPClient 或降级模式 NoOpMCPClient）
            circuit_breaker_registry: 熔断器注册表（可选，默认创建新实例）
            tool_registry: 本地工具注册表（可选）
            enable_tool_guard: 是否启用工具护栏（默认 True）
            tool_rate_limit: 是否启用速率限制（默认 True，仅护栏开启时生效）
            guard_config: 护栏自定义配置（可选）
        """
        self._mcp_client: Optional[Union[MCPClient, NoOpMCPClient]] = mcp_client
        self._available_tools: List[Dict[str, Any]] = []
        self._tool_name_set: set = set()
        self._circuit_breaker = circuit_breaker_registry or CircuitBreakerRegistry()
        self._tool_registry = tool_registry or ToolRegistry()

        # 工具护栏四层拦截
        self._enable_tool_guard = enable_tool_guard
        guard_config = guard_config or {}
        self._audit_log = AuditLog() if enable_tool_guard else None
        self._validator = ToolArgumentValidator() if enable_tool_guard else None
        self._sensitive_guard = SensitiveOperationGuard(
            policies=guard_config.get("policies"),
            audit_log=self._audit_log,
        ) if enable_tool_guard else None
        self._rate_limiter = ToolRateLimiter(
            enabled=tool_rate_limit,
            config=guard_config.get("rate_limits"),
        ) if enable_tool_guard else None

        # 如果 MCP Client 已连接且有工具缓存，自动加载
        if mcp_client is not None and hasattr(mcp_client, "tools") and mcp_client.tools:
            self._load_tools_from_cache(mcp_client.tools)

        logger.info(
            "工具分发器初始化: mcp_client=%s, tools=%d, tool_guard=%s",
            "connected" if (mcp_client and mcp_client.is_connected) else "none",
            len(self._available_tools),
            "enabled" if enable_tool_guard else "disabled",
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
        session_id: str = "",
    ) -> str:
        """分发工具调用到 MCP Server（含工具护栏、熔断检查和自动重试）

        护栏流程：工具名校验 → Schema 参数校验 → 敏感操作守卫 → 速率限制
        → 熔断检查 → 重试调用。

        Args:
            tool_name: 工具名称（如 'get_match_details'）
            args: 工具参数字典
            session_id: 会话 ID（用于敏感确认与限速的会话隔离）

        Returns:
            str: 工具执行结果文本

        Raises:
            ToolArgumentError: 参数校验失败
            ConfirmationRequired: 敏感操作需要用户确认
            ToolBlockedError: 敏感操作被策略阻断
            RateLimitExceeded: 工具调用频率超限
            ValueError: 工具名不在可用列表中
            MCPConnectionError: MCP 连接错误（重试耗尽后抛出）
            RuntimeError: MCP Client 未连接
        """
        # ── 工具护栏：参数校验 → 敏感守卫 → 限速 ──
        if self._enable_tool_guard:
            schema = self._resolve_schema(tool_name)
            result = self._validator.validate(tool_name, args, schema)
            if not result.valid:
                self._audit_log.record(
                    tool_name, args, "rejected", "; ".join(result.errors), session_id,
                )
                raise ToolArgumentError(result.errors)
            args = result.normalized_args

            decision, reason = self._sensitive_guard.check(tool_name, args, session_id)
            if decision == SensitiveOperationGuard.CONFIRM:
                raise ConfirmationRequired(tool_name, args, reason)
            if decision == SensitiveOperationGuard.BLOCK:
                raise ToolBlockedError(tool_name, reason)

            allowed, wait = self._rate_limiter.allow(tool_name, session_id)
            if not allowed:
                self._audit_log.record(
                    tool_name, args, "rate_limited", f"需等待 {wait:.0f}s", session_id,
                )
                raise RateLimitExceeded(tool_name, wait)

            self._audit_log.record(tool_name, args, "allowed", "", session_id)

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

    def confirm_tool(self, tool_name: str, session_id: str = "") -> None:
        """标记工具在某会话内已确认（由上层确认回调调用）

        Args:
            tool_name: 工具名称
            session_id: 会话 ID
        """
        if self._sensitive_guard is not None:
            self._sensitive_guard.confirm(tool_name, session_id)
            logger.info("工具已确认放行: tool=%s, session=%s", tool_name, session_id)

    @property
    def audit_log(self) -> Optional[AuditLog]:
        """工具调用审计日志（护栏启用时可用）"""
        return self._audit_log

    @property
    def tool_guard_enabled(self) -> bool:
        """工具护栏是否启用"""
        return self._enable_tool_guard

    def _resolve_schema(self, tool_name: str) -> Dict[str, Any]:
        """解析工具参数 schema（本地 ToolSchema 或 MCP inputSchema）

        返回 JSON Schema 风格 dict：{type, properties, required}。
        本地工具优先，其次查 MCP 工具列表，未找到返回空 schema。

        Args:
            tool_name: 工具名称

        Returns:
            Dict[str, Any]: 工具参数 schema
        """
        local = self._tool_registry.get_tool(tool_name)
        if local is not None:
            return {
                "type": "object",
                "properties": dict(local.schema.properties),
                "required": list(local.schema.required),
            }
        for tool in self._available_tools:
            if tool.get("name") == tool_name:
                schema = tool.get("schema") or {}
                return schema if isinstance(schema, dict) else {}
        return {}

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
