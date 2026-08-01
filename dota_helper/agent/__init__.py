"""ReAct Agent 模块 — LLM 驱动的推理引擎

实现 Thought → Action → Observation 推理循环，
通过 MCP 工具分发器调用 53 个 Dota 2 分析工具。

扩展性组件：
- Plugin / PluginRegistry: 生命周期钩子 + 中间件管道
- ToolRegistry: 本地工具注册机制
- MessageBus: Agent 间消息总线
"""
from dota_helper.agent.plugin import Plugin, PluginRegistry
from dota_helper.agent.react_agent import DotaHelperReActAgent
from dota_helper.agent.tool_dispatcher import ToolDispatcher
from dota_helper.agent.tool_registry import ToolRegistry
from dota_helper.agent.message_bus import MessageBus, EventType, Message

__all__ = [
    "DotaHelperReActAgent",
    "ToolDispatcher",
    "Plugin",
    "PluginRegistry",
    "ToolRegistry",
    "MessageBus",
    "EventType",
    "Message",
]
