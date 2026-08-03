"""ToolDispatcher — 将 Agent 的 Action 分发到本地工具注册表

M1 为本地同步工具分发（MCP Server 在 M4 接入）。
工具以 {name: Callable} 注册，可被 ReAct 循环调用。
"""
from __future__ import annotations

import inspect
from typing import Any, Callable

from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.tool_dispatcher")


class ToolDispatcher:
    """本地工具分发器"""

    def __init__(self, tools: dict[str, Callable[..., str]] | None = None) -> None:
        self._tools: dict[str, Callable[..., str]] = dict(tools or {})

    def register(self, name: str, func: Callable[..., str]) -> None:
        self._tools[name] = func

    def validate_tool(self, tool_name: str) -> bool:
        return tool_name in self._tools

    def dispatch(self, tool_name: str, args: dict[str, Any] | None = None) -> str:
        """调用工具并返回文本结果。工具不存在抛 ValueError。"""
        args = args or {}
        func = self._tools.get(tool_name)
        if func is None:
            raise ValueError(f"工具 '{tool_name}' 未注册")
        logger.info("分发工具: %s args=%s", tool_name, args)
        return str(func(**args))

    def get_tool_descriptions(self) -> str:
        """生成可注入 System Prompt 的工具描述"""
        lines = []
        for name, func in self._tools.items():
            sig = inspect.signature(func)
            params = ", ".join(sig.parameters)
            lines.append(f"- {name}({params})")
        return "\n".join(lines) if lines else "（暂无可用工具）"

    @property
    def tool_count(self) -> int:
        return len(self._tools)