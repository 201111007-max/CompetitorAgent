"""MCP Client 数据类型定义

包含工具描述信息、连接错误等核心数据模型。
"""
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class ToolInfo:
    """MCP 工具描述信息

    对应 MCP SDK 的 mcp.types.Tool，提取 Agent 所需的关键字段。

    Attributes:
        name: 工具名称（如 'get_match_details'）
        description: 工具功能描述
        parameters: JSON Schema 参数定义（对应 Tool.inputSchema）
    """
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（供 ToolDispatcher 使用）

        Returns:
            Dict[str, Any]: 包含 name/description/schema 的字典
        """
        return {
            "name": self.name,
            "description": self.description,
            "schema": self.parameters,
        }


class MCPConnectionError(Exception):
    """MCP 连接错误

    当 MCP Server 启动失败、连接断开或通信超时时抛出。

    Attributes:
        reason: 错误原因分类
        detail: 详细错误信息
    """
    STARTUP_FAILED = "startup_failed"
    CONNECTION_LOST = "connection_lost"
    TIMEOUT = "timeout"
    SDK_UNAVAILABLE = "sdk_unavailable"

    def __init__(self, reason: str, detail: str = "") -> None:
        """初始化 MCP 连接错误

        Args:
            reason: 错误原因（使用类常量）
            detail: 详细错误信息
        """
        self.reason = reason
        self.detail = detail
        super().__init__(f"MCPConnectionError({reason}): {detail}")
