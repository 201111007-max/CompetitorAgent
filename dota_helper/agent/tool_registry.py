"""本地工具注册机制 — register_tool API + 复合操作

支持注册本地 Python 函数作为 Agent 工具，无需经过 MCP Server。
ToolDispatcher 分发时优先查本地工具，再查 MCP 工具。
"""
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Awaitable, Union

from dota_helper.observability.logger import get_logger

logger = get_logger("agent.tool_registry")

# 工具处理函数类型：同步或异步，接收 args: Dict 返回 str
ToolHandler = Union[
    Callable[[Dict[str, Any]], str],
    Callable[[Dict[str, Any]], Awaitable[str]],
]


@dataclass
class ToolSchema:
    """工具参数 schema 定义"""
    type: str = "object"
    properties: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    required: List[str] = field(default_factory=list)


@dataclass
class LocalTool:
    """本地工具定义"""
    name: str
    description: str
    handler: ToolHandler
    schema: ToolSchema = field(default_factory=ToolSchema)
    is_async: bool = False


class ToolRegistry:
    """本地工具注册表

    管理通过 register_tool() API 注册的本地工具。
    支持同步和异步处理函数。
    """

    def __init__(self) -> None:
        self._tools: Dict[str, LocalTool] = {}
        logger.info("本地工具注册表初始化")

    def register(
        self,
        name: str,
        handler: ToolHandler,
        description: str = "",
        schema: Optional[Dict[str, Any]] = None,
    ) -> str:
        """注册本地工具

        Args:
            name: 工具名称（唯一标识）
            handler: 处理函数（同步或异步，接收 args: Dict 返回 str）
            description: 工具描述（用于 LLM 提示词）
            schema: 参数 schema（可选，格式同 JSON Schema）

        Returns:
            str: 工具名称

        Raises:
            ValueError: 同名工具已注册
        """
        if name in self._tools:
            raise ValueError(f"本地工具 '{name}' 已注册")

        # 自动检测是否为异步函数
        is_async = inspect.iscoroutinefunction(handler)

        # 构建 schema
        tool_schema = ToolSchema()
        if schema:
            tool_schema.properties = schema.get("properties", {})
            tool_schema.required = schema.get("required", [])

        self._tools[name] = LocalTool(
            name=name,
            description=description,
            handler=handler,
            schema=tool_schema,
            is_async=is_async,
        )
        logger.info("本地工具已注册: %s (async=%s)", name, is_async)
        return name

    def unregister(self, name: str) -> bool:
        """卸载本地工具

        Args:
            name: 工具名称

        Returns:
            bool: 是否成功卸载
        """
        if name in self._tools:
            del self._tools[name]
            logger.info("本地工具已卸载: %s", name)
            return True
        logger.warning("本地工具未找到，无法卸载: %s", name)
        return False

    def get_tool(self, name: str) -> Optional[LocalTool]:
        """获取本地工具定义

        Args:
            name: 工具名称

        Returns:
            Optional[LocalTool]: 工具定义，未找到返回 None
        """
        return self._tools.get(name)

    def has_tool(self, name: str) -> bool:
        """检查本地工具是否存在

        Args:
            name: 工具名称

        Returns:
            bool: 是否存在
        """
        return name in self._tools

    async def call_tool(self, name: str, args: Dict[str, Any]) -> str:
        """调用本地工具

        Args:
            name: 工具名称
            args: 工具参数

        Returns:
            str: 工具执行结果

        Raises:
            ValueError: 工具不存在
        """
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"本地工具 '{name}' 不存在")

        try:
            if tool.is_async:
                result = await tool.handler(args)  # type: ignore[misc]
            else:
                result = tool.handler(args)
            return str(result)
        except Exception as e:
            logger.error("本地工具调用失败: tool=%s, error=%s", name, str(e))
            raise

    def get_descriptions(self) -> str:
        """获取所有本地工具的格式化描述（用于注入系统提示词）

        Returns:
            str: 格式化的工具描述文本
        """
        if not self._tools:
            return ""

        descriptions = []
        for name, tool in self._tools.items():
            desc = f"- {name}: {tool.description}"
            if tool.schema.properties:
                param_strs = []
                for param_name, param_info in tool.schema.properties.items():
                    param_type = param_info.get("type", "any")
                    param_desc = param_info.get("description", "")
                    required = "（必填）" if param_name in tool.schema.required else "（可选）"
                    param_strs.append(f"  - {param_name} ({param_type}){required}: {param_desc}")
                desc += "\n" + "\n".join(param_strs)
            descriptions.append(desc)

        return "\n".join(descriptions)

    @property
    def tool_names(self) -> List[str]:
        """所有已注册的本地工具名称列表"""
        return list(self._tools.keys())

    @property
    def count(self) -> int:
        """已注册的本地工具数量"""
        return len(self._tools)

    def clear(self) -> None:
        """清空所有本地工具"""
        self._tools.clear()
        logger.info("本地工具注册表已清空")
