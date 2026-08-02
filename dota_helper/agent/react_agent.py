"""DotaHelperReActAgent 主类 — LLM 驱动的 Thought → Action → Observation 循环

接口签名遵循 MockReActAgent 的 run_stream() 契约，确保平滑替换。

生命周期：
1. create() 工厂方法 → 一步初始化 Agent + MCP Client + SessionManager
2. __aenter__ → 连接 MCP Server、加载会话
3. run_stream() → 流式执行 ReAct 循环，产出 SSE 事件流
4. __aexit__ → 关闭 MCP 连接、保存会话
"""
import uuid
from typing import Any, AsyncGenerator, Dict, Optional

from dota_helper.agent.injection_guard import OutputGuard, PromptInjectionDetector
from dota_helper.agent.plugin import PluginRegistry
from dota_helper.agent.rag_engine import RagEngine
from dota_helper.agent.rag_plugin import RagPlugin
from dota_helper.agent.react_loop import ReActLoop, ReActContext
from dota_helper.agent.response_parser import ResponseParser
from dota_helper.agent.session_manager import SessionManager
from dota_helper.agent.tool_dispatcher import ToolDispatcher
from dota_helper.agent.tool_guard import ToolConfirmationProvider
from dota_helper.agent.prompts.react_system import ReactSystemPrompt
from dota_helper.interfaces.llm import ILLMClient
from dota_helper.llm.client import LLMClient
from dota_helper.mcp_client.client import MCPClient, NoOpMCPClient
from dota_helper.mcp_client.types import MCPConnectionError
from dota_helper.orchestrator.review_config import ReviewConfig
from dota_helper.observability.logger import get_logger

logger = get_logger("agent.react_agent")


class DotaHelperReActAgent:
    """ReAct Agent 主类，LLM 驱动的 Thought → Action → Observation 循环

    通过依赖注入接收 LLM 客户端、工具分发器和会话管理器，
    执行完整的 ReAct 推理循环并产出 SSE 事件流。

    与 MockReActAgent 的 run_stream() 签名完全一致，支持平滑替换。

    Args:
        llm_client: LLM 客户端（ILLMClient 协议）
        tool_dispatcher: MCP 工具分发器
        session_manager: 会话持久化管理器
        config: 可选的复盘配置
        enable_mcp: 是否启用 MCP 连接（由 create() 工厂方法设置）
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        tool_dispatcher: ToolDispatcher,
        session_manager: SessionManager,
        config: Optional[ReviewConfig] = None,
        enable_mcp: bool = True,
        enable_rag: bool = True,
        rag_engine: Optional[RagEngine] = None,
        plugin_registry: Optional[PluginRegistry] = None,
        enable_injection_guard: bool = True,
        enable_tool_guard: bool = True,
        tool_rate_limit: bool = True,
        confirmation_provider: Optional[ToolConfirmationProvider] = None,
    ) -> None:
        """初始化 ReAct Agent

        Args:
            llm_client: LLM 客户端（遵循 ILLMClient 协议）
            tool_dispatcher: MCP 工具分发器
            session_manager: 会话持久化管理器
            config: 可选的复盘配置（默认使用 ReviewConfig()）
            enable_mcp: 是否启用 MCP 连接（默认 True）
            enable_rag: 是否启用 RAG 知识注入（默认 True）
            rag_engine: 自定义 RagEngine 实例（默认自动创建）
            plugin_registry: 自定义 PluginRegistry 实例（默认自动创建）
            enable_injection_guard: 是否启用提示注入防御（默认 True）
            enable_tool_guard: 是否启用工具护栏（默认 True；仅作用于注入的
                ToolDispatcher 在构造时开启的情况）
            tool_rate_limit: 是否启用速率限制（默认 True）
            confirmation_provider: 敏感操作确认回调（可选）
        """
        self._llm_client = llm_client
        self._tool_dispatcher = tool_dispatcher
        self._session_manager = session_manager
        self._config = config or ReviewConfig()
        self._enable_mcp = enable_mcp
        self._enable_rag = enable_rag
        self._enable_injection_guard = enable_injection_guard
        self._enable_tool_guard = enable_tool_guard
        self._tool_rate_limit = tool_rate_limit

        # 初始化子组件
        self._parser = ResponseParser()
        self._prompt_builder = ReactSystemPrompt()

        # 初始化插件注册表
        self._plugin_registry = plugin_registry or PluginRegistry()

        # 初始化 RAG 引擎并注册 RagPlugin
        self._rag_engine = rag_engine
        if enable_rag:
            if self._rag_engine is None:
                self._rag_engine = RagEngine()
            self._rag_plugin = RagPlugin(
                engine=self._rag_engine,
                injection_detector=PromptInjectionDetector() if enable_injection_guard else None,
            )
            self._plugin_registry.register(self._rag_plugin)
            logger.info("RAG 插件已注册到 Agent")
        else:
            self._rag_engine = None
            self._rag_plugin = None

        # 构建推理循环控制器
        injection_detector = PromptInjectionDetector() if enable_injection_guard else None
        output_guard = OutputGuard() if enable_injection_guard else None

        self._loop = ReActLoop(
            llm_client=self._llm_client,
            tool_dispatcher=self._tool_dispatcher,
            parser=self._parser,
            prompt_builder=self._prompt_builder,
            plugin_registry=self._plugin_registry,
            injection_detector=injection_detector,
            output_guard=output_guard,
            confirmation_provider=confirmation_provider,
            max_iterations=self._config.max_tokens // 500,  # 启发式：约 15 次迭代
            max_tokens=self._config.max_tokens * 10,  # Agent 可用 Token 为配置的 10 倍
        )

        self._closed = False
        logger.info(
            "ReAct Agent 初始化: model=%s, max_tokens=%d, enable_mcp=%s, enable_rag=%s, "
            "tool_guard=%s, tool_rate_limit=%s",
            self._config.model,
            self._config.max_tokens,
            enable_mcp,
            enable_rag,
            enable_tool_guard,
            tool_rate_limit,
        )

    async def __aenter__(self) -> "DotaHelperReActAgent":
        """初始化资源：连接 MCP Server、加载会话

        当 enable_mcp=True 时，通过 ToolDispatcher 连接 MCP Server，
        获取 53 个工具描述。连接失败时自动降级为无工具模式。

        Returns:
            DotaHelperReActAgent: self
        """
        logger.info("ReAct Agent 进入异步上下文")

        if self._enable_mcp and not self._tool_dispatcher.is_connected:
            try:
                await self._tool_dispatcher.connect()
                logger.info(
                    "MCP Server 连接成功: tools=%d",
                    self._tool_dispatcher.tool_count,
                )
            except MCPConnectionError as e:
                logger.warning(
                    "MCP Server 连接失败，降级为无工具模式: %s",
                    str(e),
                )
            except Exception as e:
                logger.warning(
                    "MCP Server 连接异常，降级为无工具模式: %s",
                    str(e),
                )

        return self

    async def __aexit__(self, *args: Any) -> None:
        """释放资源：关闭 MCP 连接、保存会话"""
        if self._enable_mcp and self._tool_dispatcher.is_connected:
            try:
                await self._tool_dispatcher.disconnect()
            except Exception as e:
                logger.debug("MCP 断开连接异常（可忽略）: %s", str(e))

        self._closed = True
        logger.info("ReAct Agent 退出异步上下文")

    async def run_stream(
        self,
        message: str,
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式执行 ReAct 循环，产出事件流

        与 MockReActAgent.run_stream() 签名一致，支持平滑替换。
        产出 9 种事件类型：session/thought/action/observation/final/
        progress/phase_complete/report/error

        Args:
            message: 用户输入消息
            session_id: 已有会话 ID（可选，为空则创建新会话）

        Yields:
            Dict[str, Any]: SSE 事件字典
        """
        if self._closed:
            logger.warning("Agent 已关闭，拒绝请求")
            return

        # 确定会话 ID
        if not session_id:
            session_id = await self._session_manager.create_session()
        else:
            session = await self._session_manager.get_session(session_id)
            if session is None:
                # 前端传了不存在的 session_id，自动创建
                session_id = await self._session_manager.create_session()

        # 构建推理上下文
        session = await self._session_manager.get_session(session_id)
        existing_messages = []
        if session is not None:
            # 将历史消息转为 OpenAI 风格
            for msg in session.messages:
                role = "assistant" if msg.role == "agent" else msg.role
                existing_messages.append({"role": role, "content": msg.content})

        # 使用会话管理器的 data_dir 作为 checkpoint 目录
        checkpoint_dir = str(self._session_manager.data_dir)

        context = ReActContext(
            session_id=session_id,
            messages=existing_messages,
            checkpoint_dir=checkpoint_dir,
        )

        # 追加用户消息到会话
        await self._session_manager.append_message(
            session_id=session_id,
            role="user",
            content=message,
        )

        logger.info(
            "ReAct 循环开始: session=%s, message_len=%d",
            session_id,
            len(message),
        )

        # 执行推理循环
        final_content = ""
        async for event in self._loop.execute(
            initial_message=message,
            context=context,
        ):
            yield event

            # 捕获 final 事件内容用于持久化
            if event.get("type") == "final":
                final_content = event.get("content", "")

        # 推理完成，清理 checkpoint
        context.clear_checkpoint()

        # 持久化 Agent 回答
        if final_content:
            conversation_id = context.conversation_id or f"conv_{uuid.uuid4().hex[:12]}"
            await self._session_manager.append_message(
                session_id=session_id,
                role="agent",
                content=final_content,
                conversation_id=conversation_id,
            )

        logger.info("ReAct 循环结束: session=%s", session_id)

    @classmethod
    async def create(
        cls,
        config: Optional[ReviewConfig] = None,
        enable_mcp: bool = True,
        enable_rag: bool = True,
        rag_engine: Optional[RagEngine] = None,
        enable_injection_guard: bool = True,
        enable_tool_guard: bool = True,
        tool_rate_limit: bool = True,
        confirmation_provider: Optional[ToolConfirmationProvider] = None,
    ) -> "DotaHelperReActAgent":
        """工厂方法：一步初始化 Agent + MCP Client + SessionManager

        Args:
            config: 可选的复盘配置
            enable_mcp: 是否启用 MCP 工具连接（默认 True）
                - True: 创建 MCPClient，连接 MCP Server 获取 53 工具
                - False: 创建 NoOpMCPClient，降级为无工具模式
            enable_rag: 是否启用 RAG 知识注入（默认 True）
            rag_engine: 自定义 RagEngine 实例（默认自动创建）
            enable_injection_guard: 是否启用提示注入防御（默认 True）
            enable_tool_guard: 是否启用工具护栏（默认 True）
                - True: 参数校验/敏感守卫/限速/审计全部生效
                - False: 全部关闭（本地调试可关）
            tool_rate_limit: 是否启用速率限制（默认 True）
                - False: 仅关闭限速层，参数校验/敏感守卫/审计不受影响
            confirmation_provider: 敏感操作确认回调（可选）

        Returns:
            DotaHelperReActAgent: 已初始化的 Agent 实例
        """
        config = config or ReviewConfig()

        # 初始化 LLM 客户端
        llm_client = LLMClient()

        # 初始化 MCP Client 和工具分发器
        if enable_mcp:
            try:
                mcp_client = MCPClient()
                logger.info("MCP Client 已创建（待连接）")
            except Exception as e:
                logger.warning("MCP Client 创建失败，降级为 NoOp: %s", str(e))
                mcp_client = NoOpMCPClient(reason=f"创建失败: {e}")
        else:
            mcp_client = NoOpMCPClient(reason="enable_mcp=False")
            logger.info("MCP Client 降级模式: enable_mcp=False")

        # 创建工具分发器（注入 MCP Client + 工具护栏配置）
        tool_dispatcher = ToolDispatcher(
            mcp_client=mcp_client,
            enable_tool_guard=enable_tool_guard,
            tool_rate_limit=tool_rate_limit,
        )

        # 初始化会话管理器
        data_dir = None
        if config.memory.data_dir:
            from pathlib import Path
            data_dir = Path(config.memory.data_dir)
        session_manager = SessionManager(data_dir=data_dir)

        # 创建 Agent 实例
        agent = cls(
            llm_client=llm_client,
            tool_dispatcher=tool_dispatcher,
            session_manager=session_manager,
            config=config,
            enable_mcp=enable_mcp,
            enable_rag=enable_rag,
            rag_engine=rag_engine,
            enable_injection_guard=enable_injection_guard,
            enable_tool_guard=enable_tool_guard,
            tool_rate_limit=tool_rate_limit,
            confirmation_provider=confirmation_provider,
        )

        logger.info(
            "ReAct Agent 工厂创建完成: enable_mcp=%s, enable_rag=%s, tool_guard=%s, "
            "tool_rate_limit=%s, mcp_type=%s",
            enable_mcp, enable_rag,
            enable_tool_guard, tool_rate_limit,
            "MCPClient" if enable_mcp else "NoOpMCPClient",
        )
        return agent
