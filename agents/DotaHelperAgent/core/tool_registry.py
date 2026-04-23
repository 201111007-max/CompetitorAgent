"""工具注册表 - 管理 Agent 可用的所有 Tools"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

try:
    from ..tools.base import Tool, ToolResult
except ImportError:
    try:
        from tools.base import Tool, ToolResult
    except ImportError:
        from agents.DotaHelperAgent.tools.base import Tool, ToolResult


@dataclass
class ToolCall:
    """工具调用记录"""
    tool_name: str
    parameters: Dict[str, Any]
    result: Optional[ToolResult] = None
    timestamp: float = 0.0


class ToolRegistry:
    """工具注册表

    管理 Agent 可用的所有 Tools，支持按名称、类别检索，
    记录工具调用历史供 Agent 反思使用。
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._tools_by_category: Dict[str, List[Tool]] = {}
        self._call_history: List[ToolCall] = []

    def register(self, tool: Tool) -> None:
        """注册 Tool"""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")

        self._tools[tool.name] = tool

        if tool.category not in self._tools_by_category:
            self._tools_by_category[tool.category] = []
        self._tools_by_category[tool.category].append(tool)

    def register_batch(self, tools: List[Tool]) -> None:
        """批量注册 Tools"""
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> Optional[Tool]:
        """获取 Tool"""
        return self._tools.get(name)

    def get_by_category(self, category: str) -> List[Tool]:
        """按类别获取 Tools"""
        return self._tools_by_category.get(category, [])

    def list_tools(self) -> List[str]:
        """列出所有 Tool 名称"""
        return list(self._tools.keys())

    def list_categories(self) -> List[str]:
        """列出所有类别"""
        return list(self._tools_by_category.keys())

    def execute(self, tool_name: str, **kwargs) -> ToolResult:
        """执行 Tool"""
        tool = self.get(tool_name)
        if tool is None:
            return ToolResult(
                tool_name=tool_name,
                status="failure",
                data=None,
                error=f"Tool '{tool_name}' not found"
            )

        result = tool.execute(**kwargs)

        self._call_history.append(ToolCall(
            tool_name=tool_name,
            parameters=kwargs,
            result=result,
            timestamp=result.timestamp
        ))

        return result

    def get_call_history(self, limit: int = 10) -> List[ToolCall]:
        """获取调用历史"""
        return self._call_history[-limit:]

    def clear_history(self) -> None:
        """清空调用历史"""
        self._call_history.clear()

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools