"""插件系统 — 生命周期钩子 + 中间件管道

支持在 ReAct 循环的关键节点注入自定义行为：
- before_llm_call / after_llm_call: LLM 调用前后
- before_action / after_action: 工具调用前后
- on_error: 错误发生时
- on_start / on_end: 推理循环开始/结束
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Callable, Awaitable

from dota_helper.observability.logger import get_logger

logger = get_logger("agent.plugin")


class Plugin(ABC):
    """插件基类

    子类重写需要的钩子方法即可，无需实现全部接口。
    """

    @property
    def name(self) -> str:
        """插件名称（默认使用类名）"""
        return self.__class__.__name__

    async def on_start(self, context: Dict[str, Any]) -> None:
        """推理循环开始时的钩子

        Args:
            context: 推理上下文（包含 session_id, conversation_id, messages 等）
        """
        pass

    async def on_end(self, context: Dict[str, Any]) -> None:
        """推理循环结束时的钩子

        Args:
            context: 推理上下文
        """
        pass

    async def before_llm_call(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """LLM 调用前的钩子

        可修改消息列表（如注入额外上下文、添加系统指令）。

        Args:
            messages: 当前消息列表

        Returns:
            List[Dict[str, str]]: 修改后的消息列表
        """
        return messages

    async def after_llm_call(self, llm_output: str) -> str:
        """LLM 调用后的钩子

        可修改 LLM 输出（如后处理、格式化）。

        Args:
            llm_output: LLM 原始输出

        Returns:
            str: 修改后的输出
        """
        return llm_output

    async def before_action(self, tool_name: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """工具调用前的钩子

        可修改参数或阻止调用（返回 None 表示阻止）。

        Args:
            tool_name: 工具名称
            args: 工具参数

        Returns:
            Optional[Dict[str, Any]]: 修改后的参数，None 表示阻止调用
        """
        return args

    async def after_action(self, tool_name: str, args: Dict[str, Any], result: str) -> str:
        """工具调用后的钩子

        可修改工具返回结果。

        Args:
            tool_name: 工具名称
            args: 工具参数
            result: 工具返回结果

        Returns:
            str: 修改后的结果
        """
        return result

    async def on_error(self, error: Exception, context: str = "") -> None:
        """错误发生时的钩子

        Args:
            error: 异常对象
            context: 错误上下文描述
        """
        pass


class PluginRegistry:
    """插件注册表

    管理插件的注册、卸载，以及在 ReAct 循环中分发生命周期事件。
    支持按优先级排序执行。
    """

    def __init__(self) -> None:
        self._plugins: Dict[str, Plugin] = {}
        self._order: List[str] = []  # 按注册顺序
        logger.info("插件注册表初始化")

    def register(self, plugin: Plugin, name: Optional[str] = None) -> str:
        """注册插件

        Args:
            plugin: 插件实例
            name: 可选的自定义名称（默认使用 plugin.name）

        Returns:
            str: 插件注册名称

        Raises:
            ValueError: 同名插件已注册
        """
        plugin_name = name or plugin.name
        if plugin_name in self._plugins:
            raise ValueError(f"插件 '{plugin_name}' 已注册")
        self._plugins[plugin_name] = plugin
        self._order.append(plugin_name)
        logger.info("插件已注册: %s (%s)", plugin_name, type(plugin).__name__)
        return plugin_name

    def unregister(self, name: str) -> bool:
        """卸载插件

        Args:
            name: 插件名称

        Returns:
            bool: 是否成功卸载
        """
        if name in self._plugins:
            del self._plugins[name]
            self._order = [n for n in self._order if n != name]
            logger.info("插件已卸载: %s", name)
            return True
        logger.warning("插件未找到，无法卸载: %s", name)
        return False

    def get_plugin(self, name: str) -> Optional[Plugin]:
        """获取已注册的插件实例

        Args:
            name: 插件名称

        Returns:
            Optional[Plugin]: 插件实例，未找到返回 None
        """
        return self._plugins.get(name)

    @property
    def plugins(self) -> Dict[str, Plugin]:
        """所有已注册的插件"""
        return dict(self._plugins)

    @property
    def count(self) -> int:
        """已注册的插件数量"""
        return len(self._plugins)

    # ── 生命周期事件分发 ──

    async def dispatch_on_start(self, context: Dict[str, Any]) -> None:
        """分发 on_start 事件"""
        for name in self._order:
            plugin = self._plugins[name]
            try:
                await plugin.on_start(context)
            except Exception as e:
                logger.warning("插件 on_start 失败: plugin=%s, error=%s", name, str(e))

    async def dispatch_on_end(self, context: Dict[str, Any]) -> None:
        """分发 on_end 事件"""
        for name in self._order:
            plugin = self._plugins[name]
            try:
                await plugin.on_end(context)
            except Exception as e:
                logger.warning("插件 on_end 失败: plugin=%s, error=%s", name, str(e))

    async def dispatch_before_llm_call(
        self, messages: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """分发 before_llm_call 事件（管道模式，依次传递）"""
        current = messages
        for name in self._order:
            plugin = self._plugins[name]
            try:
                current = await plugin.before_llm_call(current)
            except Exception as e:
                logger.warning("插件 before_llm_call 失败: plugin=%s, error=%s", name, str(e))
        return current

    async def dispatch_after_llm_call(self, llm_output: str) -> str:
        """分发 after_llm_call 事件（管道模式，依次传递）"""
        current = llm_output
        for name in self._order:
            plugin = self._plugins[name]
            try:
                current = await plugin.after_llm_call(current)
            except Exception as e:
                logger.warning("插件 after_llm_call 失败: plugin=%s, error=%s", name, str(e))
        return current

    async def dispatch_before_action(
        self, tool_name: str, args: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """分发 before_action 事件

        任一插件返回 None 则阻止调用。

        Args:
            tool_name: 工具名称
            args: 工具参数

        Returns:
            Optional[Dict[str, Any]]: 最终参数，None 表示被阻止
        """
        current_args = args
        for name in self._order:
            plugin = self._plugins[name]
            try:
                result = await plugin.before_action(tool_name, current_args)
                if result is None:
                    logger.info("插件阻止了工具调用: plugin=%s, tool=%s", name, tool_name)
                    return None
                current_args = result
            except Exception as e:
                logger.warning("插件 before_action 失败: plugin=%s, error=%s", name, str(e))
        return current_args

    async def dispatch_after_action(
        self, tool_name: str, args: Dict[str, Any], result: str
    ) -> str:
        """分发 after_action 事件（管道模式，依次传递）"""
        current = result
        for name in self._order:
            plugin = self._plugins[name]
            try:
                current = await plugin.after_action(tool_name, args, current)
            except Exception as e:
                logger.warning("插件 after_action 失败: plugin=%s, error=%s", name, str(e))
        return current

    async def dispatch_on_error(self, error: Exception, context: str = "") -> None:
        """分发 on_error 事件"""
        for name in self._order:
            plugin = self._plugins[name]
            try:
                await plugin.on_error(error, context)
            except Exception as e:
                logger.warning("插件 on_error 失败: plugin=%s, error=%s", name, str(e))
