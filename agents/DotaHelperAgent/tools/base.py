"""Tool 基类定义"""

from dataclasses import dataclass, field
from typing import Dict, Any, Callable, Optional, List
from enum import Enum
import time


class ToolStatus(Enum):
    """工具执行状态"""
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


@dataclass
class ToolResult:
    """工具执行结果"""
    tool_name: str
    status: ToolStatus
    data: Any
    error: Optional[str] = None
    execution_time: float = 0.0
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_success(self) -> bool:
        return self.status == ToolStatus.SUCCESS

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "status": self.status.value,
            "data": self.data,
            "error": self.error,
            "execution_time": self.execution_time,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }


@dataclass
class Tool:
    """Tool 定义

    用于封装分析器、推荐器等为标准接口，供 Agent 自主决策调用。
    """
    name: str
    description: str
    parameters: Dict[str, type]
    func: Callable
    output_type: type = None
    examples: List[str] = field(default_factory=list)
    category: str = "general"

    def __post_init__(self):
        if not self.name:
            raise ValueError("Tool name cannot be empty")
        if not callable(self.func):
            raise ValueError("Tool function must be callable")

    def execute(self, **kwargs) -> ToolResult:
        """执行工具"""
        start_time = time.time()
        try:
            result = self.func(**kwargs)
            execution_time = time.time() - start_time
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                data=result,
                execution_time=execution_time
            )
        except Exception as e:
            execution_time = time.time() - start_time
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.FAILURE,
                data=None,
                error=str(e),
                execution_time=execution_time
            )

    def get_schema(self) -> Dict[str, Any]:
        """获取 Tool 的 JSON Schema"""
        properties = {}
        required = []

        for param_name, param_type in self.parameters.items():
            type_str = "string"
            if param_type == int:
                type_str = "integer"
            elif param_type == float:
                type_str = "number"
            elif param_type == bool:
                type_str = "boolean"
            elif param_type == list:
                type_str = "array"
            elif param_type == dict:
                type_str = "object"

            properties[param_name] = {
                "type": type_str,
                "description": f"Parameter {param_name}"
            }
            required.append(param_name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            },
            "examples": self.examples,
            "category": self.category
        }