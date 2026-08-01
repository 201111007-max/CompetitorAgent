"""ReAct Agent 模块 — LLM 驱动的推理引擎

实现 Thought → Action → Observation 推理循环，
通过 MCP 工具分发器调用 53 个 Dota 2 分析工具。

扩展性组件：
- Plugin / PluginRegistry: 生命周期钩子 + 中间件管道
- ToolRegistry: 本地工具注册机制
- MessageBus: Agent 间消息总线
- RagEngine: Embedding + chromadb 语义检索引擎
- RagPlugin: LLM 调用前自动注入 RAG 知识的插件
"""
from dota_helper.agent.plugin import Plugin, PluginRegistry
from dota_helper.agent.react_agent import DotaHelperReActAgent
from dota_helper.agent.tool_dispatcher import ToolDispatcher
from dota_helper.agent.tool_registry import ToolRegistry
from dota_helper.agent.message_bus import MessageBus, EventType, Message
from dota_helper.agent.rag_engine import RagEngine
from dota_helper.agent.rag_plugin import RagPlugin

__all__ = [
    "DotaHelperReActAgent",
    "ToolDispatcher",
    "Plugin",
    "PluginRegistry",
    "ToolRegistry",
    "MessageBus",
    "EventType",
    "Message",
    "RagEngine",
    "RagPlugin",
]
