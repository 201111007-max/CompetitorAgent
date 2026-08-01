"""MCP Client — 连接 MCP Server 并调用工具

通过 stdio spawn MCP Server 子进程，建立 ClientSession，
提供工具发现（list_tools）和工具调用（call_tool）能力。

生命周期：
1. connect() → spawn MCP Server 子进程 + 建立 ClientSession
2. call_tool() / list_tools() → 与 MCP Server 交互
3. disconnect() → 关闭 ClientSession + 终止子进程

错误恢复：
- MCP Server 启动失败 → Agent 降级为无工具模式
- MCP Server 运行时崩溃 → 自动重连（最多 3 次，指数退避）
- 工具调用超时 → 30 秒超时，返回错误 Observation
- SDK 不可用 → 自动降级为 NoOpMCPClient
"""
import asyncio
import os
import sys
from typing import Any, Dict, List, Optional

from dota_helper.mcp_client.types import ToolInfo, MCPConnectionError
from dota_helper.observability.logger import get_logger

logger = get_logger("mcp_client.client")

# 默认 MCP Server 启动命令
_DEFAULT_SERVER_COMMAND = sys.executable  # 当前 Python 解释器
# 使用绝对路径避免子进程 CWD 问题
_DEFAULT_SERVER_SCRIPT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "run_server.py")
)
_DEFAULT_SERVER_ARGS = [_DEFAULT_SERVER_SCRIPT]

# 重连参数
_MAX_RECONNECT_ATTEMPTS = 3
_RECONNECT_BASE_DELAY = 1.0  # 秒

# 工具调用超时
_DEFAULT_CALL_TIMEOUT = 30.0  # 秒


class MCPClient:
    """MCP Client，连接 MCP Server 并调用工具

    通过 stdio 与 MCP Server 子进程通信，支持 53 个 Dota 2 工具的
    发现和调用。支持自动重连和降级策略。

    Args:
        server_command: MCP Server 启动命令（默认使用当前 Python 解释器）
        server_args: MCP Server 启动参数（默认 ['-m', 'dota_helper.mcp_server.server']）
        server_env: 传递给子进程的环境变量（可选）
        call_timeout: 工具调用超时时间（秒，默认 30）
    """

    def __init__(
        self,
        server_command: Optional[str] = None,
        server_args: Optional[List[str]] = None,
        server_env: Optional[Dict[str, str]] = None,
        call_timeout: float = _DEFAULT_CALL_TIMEOUT,
    ) -> None:
        """初始化 MCP Client

        Args:
            server_command: MCP Server 启动命令（默认当前 Python 解释器）
            server_args: MCP Server 启动参数
            server_env: 子进程环境变量
            call_timeout: 工具调用超时（秒）
        """
        self._server_command = server_command or _DEFAULT_SERVER_COMMAND
        self._server_args = server_args or _DEFAULT_SERVER_ARGS
        # 自动继承父进程的 PYTHONPATH，确保子进程能找到 dota_helper 包
        if server_env is None:
            pythonpath = os.environ.get("PYTHONPATH", "")
            if pythonpath:
                server_env = {"PYTHONPATH": pythonpath}
        self._server_env = server_env
        self._call_timeout = call_timeout

        # 连接状态
        self._connected = False
        self._session: Optional[Any] = None  # ClientSession
        self._read_stream: Optional[Any] = None
        self._write_stream: Optional[Any] = None
        self._stdio_context: Optional[Any] = None  # stdio_client 上下文
        self._session_context: Optional[Any] = None  # ClientSession 上下文

        # 工具缓存
        self._tools_cache: Optional[List[ToolInfo]] = None

        logger.info(
            "MCP Client 初始化: command=%s %s, timeout=%.1fs",
            self._server_command,
            " ".join(self._server_args),
            self._call_timeout,
        )

    async def connect(self) -> None:
        """spawn MCP Server 子进程，建立 stdio ClientSession

        执行步骤：
        1. 创建 StdioServerParameters
        2. 调用 stdio_client() 获取读写流
        3. 创建 ClientSession 并初始化
        4. 调用 session.initialize() 完成握手
        5. 调用 list_tools() 缓存工具列表

        Raises:
            MCPConnectionError: MCP Server 启动或连接失败
        """
        if self._connected:
            logger.warning("MCP Client 已连接，跳过重复连接")
            return

        try:
            from mcp.client.stdio import StdioServerParameters, stdio_client
            from mcp.client.session import ClientSession
        except ImportError as e:
            raise MCPConnectionError(
                MCPConnectionError.SDK_UNAVAILABLE,
                f"MCP SDK 不可用: {e}",
            )

        server_params = StdioServerParameters(
            command=self._server_command,
            args=self._server_args,
            env=self._server_env,
        )

        logger.info("正在连接 MCP Server: %s %s", self._server_command, " ".join(self._server_args))

        try:
            # 进入 stdio_client 上下文，获取读写流
            self._stdio_context = stdio_client(server_params)
            self._read_stream, self._write_stream = await self._stdio_context.__aenter__()

            # 创建并初始化 ClientSession
            self._session = ClientSession(self._read_stream, self._write_stream)
            self._session_context = self._session
            await self._session.__aenter__()

            # 完成 MCP 协议握手
            init_result = await self._session.initialize()
            logger.info(
                "MCP Server 连接成功: server=%s, version=%s",
                init_result.serverInfo.name if init_result.serverInfo else "unknown",
                init_result.serverInfo.version if init_result.serverInfo else "unknown",
            )

            # 缓存工具列表
            await self._refresh_tools_cache()

            self._connected = True
            logger.info("MCP Client 连接完成: tools=%d", len(self._tools_cache or []))

        except MCPConnectionError:
            raise
        except Exception as e:
            # 清理部分初始化的资源
            await self._cleanup_resources()
            raise MCPConnectionError(
                MCPConnectionError.STARTUP_FAILED,
                f"MCP Server 启动失败: {e}",
            )

    async def disconnect(self) -> None:
        """关闭 ClientSession，终止 MCP Server 子进程

        安全释放所有资源，关闭读写流和子进程。
        """
        if not self._connected and self._session is None:
            return

        logger.info("正在断开 MCP Server 连接")
        await self._cleanup_resources()
        self._connected = False
        self._session = None
        self._read_stream = None
        self._write_stream = None
        self._tools_cache = None
        logger.info("MCP Server 连接已断开")

    async def call_tool(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> str:
        """调用 MCP 工具并返回结果文本

        Args:
            name: 工具名称（如 'get_match_details'）
            arguments: 工具参数字典

        Returns:
            str: 工具执行结果文本

        Raises:
            MCPConnectionError: 连接断开或超时
            RuntimeError: Client 未连接
        """
        if not self._connected or self._session is None:
            raise MCPConnectionError(
                MCPConnectionError.CONNECTION_LOST,
                "MCP Client 未连接，请先调用 connect()",
            )

        logger.info("调用 MCP 工具: %s(%s)", name, arguments or {})

        try:
            result = await asyncio.wait_for(
                self._session.call_tool(name, arguments),
                timeout=self._call_timeout,
            )

            # 提取文本结果
            if result.isError:
                error_text = self._extract_text_content(result.content)
                logger.warning("MCP 工具返回错误: %s → %s", name, error_text[:200])
                return f"❌ 工具调用错误: {error_text}"

            text = self._extract_text_content(result.content)
            logger.debug("MCP 工具调用成功: %s, result_len=%d", name, len(text))
            return text

        except asyncio.TimeoutError:
            logger.warning("MCP 工具调用超时: %s (%.1fs)", name, self._call_timeout)
            raise MCPConnectionError(
                MCPConnectionError.TIMEOUT,
                f"工具 '{name}' 调用超时 ({self._call_timeout}s)",
            )
        except MCPConnectionError:
            raise
        except Exception as e:
            logger.error("MCP 工具调用失败: %s → %s", name, str(e))
            # 检测是否需要重连
            await self._handle_connection_error(e)
            raise MCPConnectionError(
                MCPConnectionError.CONNECTION_LOST,
                f"工具 '{name}' 调用失败: {e}",
            )

    async def list_tools(self) -> List[ToolInfo]:
        """工具发现：获取所有工具的名称+描述+参数 schema

        Returns:
            List[ToolInfo]: 工具描述列表

        Raises:
            MCPConnectionError: 连接断开
            RuntimeError: Client 未连接
        """
        if not self._connected or self._session is None:
            raise MCPConnectionError(
                MCPConnectionError.CONNECTION_LOST,
                "MCP Client 未连接，请先调用 connect()",
            )

        # 优先返回缓存
        if self._tools_cache is not None:
            return self._tools_cache

        return await self._refresh_tools_cache()

    @property
    def is_connected(self) -> bool:
        """连接状态

        Returns:
            bool: 是否已连接到 MCP Server
        """
        return self._connected

    @property
    def tools(self) -> List[ToolInfo]:
        """已缓存的工具列表

        Returns:
            List[ToolInfo]: 工具描述列表（可能为空）
        """
        return self._tools_cache or []

    # ----------------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------------

    async def _refresh_tools_cache(self) -> List[ToolInfo]:
        """刷新工具列表缓存

        Returns:
            List[ToolInfo]: 从 MCP Server 获取的工具列表
        """
        if self._session is None:
            return []

        try:
            result = await self._session.list_tools()
            self._tools_cache = [
                ToolInfo(
                    name=tool.name,
                    description=tool.description or "",
                    parameters=tool.inputSchema or {},
                )
                for tool in result.tools
            ]
            logger.info("工具列表刷新: count=%d", len(self._tools_cache))
            return self._tools_cache
        except Exception as e:
            logger.warning("获取工具列表失败: %s", str(e))
            self._tools_cache = []
            return []

    @staticmethod
    def _extract_text_content(content: Any) -> str:
        """从 MCP CallToolResult.content 提取文本

        MCP 结果的 content 是 TextContent 列表，
        每个元素有 .text 属性。

        Args:
            content: MCP 结果内容列表

        Returns:
            str: 拼接后的文本
        """
        if not content:
            return ""

        texts = []
        for item in content:
            # TextContent 类型有 .text 属性
            if hasattr(item, "text"):
                texts.append(item.text)
            elif isinstance(item, str):
                texts.append(item)
            else:
                texts.append(str(item))

        return "\n".join(texts)

    async def _cleanup_resources(self) -> None:
        """安全清理所有连接资源"""
        # 关闭 ClientSession
        if self._session_context is not None:
            try:
                await self._session_context.__aexit__(None, None, None)
            except Exception as e:
                logger.debug("关闭 ClientSession 异常（可忽略）: %s", str(e))
            self._session_context = None

        # 关闭 stdio_client（终止子进程）
        if self._stdio_context is not None:
            try:
                await self._stdio_context.__aexit__(None, None, None)
            except Exception as e:
                logger.debug("关闭 stdio_client 异常（可忽略）: %s", str(e))
            self._stdio_context = None

    async def _handle_connection_error(self, error: Exception) -> None:
        """处理连接错误，尝试自动重连

        当检测到 MCP Server 崩溃或连接断开时，
        按指数退避策略重连（最多 3 次）。

        Args:
            error: 触发重连的原始异常
        """
        logger.warning("检测到连接错误，尝试重连: %s", str(error))

        for attempt in range(1, _MAX_RECONNECT_ATTEMPTS + 1):
            delay = _RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
            logger.info("重连尝试 %d/%d（等待 %.1fs）", attempt, _MAX_RECONNECT_ATTEMPTS, delay)

            await asyncio.sleep(delay)

            try:
                # 先清理旧资源
                await self._cleanup_resources()
                self._connected = False
                self._session = None

                # 重新连接
                await self.connect()

                logger.info("重连成功（第 %d 次尝试）", attempt)
                return
            except Exception as reconnect_error:
                logger.warning(
                    "重连失败（第 %d 次）: %s",
                    attempt,
                    str(reconnect_error),
                )

        logger.error("重连全部失败（%d 次），Agent 将降级为无工具模式", _MAX_RECONNECT_ATTEMPTS)
        self._connected = False


class NoOpMCPClient:
    """无操作 MCP Client（降级模式）

    当 MCP SDK 不可用或 MCP Server 启动失败时，
    Agent 使用此降级客户端，所有工具调用返回降级提示。

    保持与 MCPClient 相同的接口签名，支持无缝替换。
    """

    def __init__(self, reason: str = "SDK 不可用") -> None:
        """初始化降级客户端

        Args:
            reason: 降级原因
        """
        self._reason = reason
        logger.info("MCP Client 降级模式: reason=%s", reason)

    async def connect(self) -> None:
        """降级模式：无操作

        Returns:
            None
        """
        logger.debug("NoOpMCPClient.connect(): 降级模式，跳过")

    async def disconnect(self) -> None:
        """降级模式：无操作

        Returns:
            None
        """
        logger.debug("NoOpMCPClient.disconnect(): 降级模式，跳过")

    async def call_tool(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> str:
        """降级模式：返回降级提示

        Args:
            name: 工具名称
            arguments: 工具参数

        Returns:
            str: 降级提示文本
        """
        return f"⚠️ MCP 工具不可用（降级模式: {self._reason}）— 无法调用 '{name}'"

    async def list_tools(self) -> List[ToolInfo]:
        """降级模式：返回空列表

        Returns:
            List[ToolInfo]: 空列表
        """
        return []

    @property
    def is_connected(self) -> bool:
        """降级模式：始终返回 False

        Returns:
            bool: False
        """
        return False

    @property
    def tools(self) -> List[ToolInfo]:
        """降级模式：返回空列表

        Returns:
            List[ToolInfo]: 空列表
        """
        return []
