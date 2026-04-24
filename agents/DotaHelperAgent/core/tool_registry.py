"""工具注册表 - 管理 Agent 可用的所有 Tools

支持标准化的 Agent Tools，提供完整的工具管理、执行和监控功能
"""

from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
import time
import json

try:
    from ..tools.base import Tool, ToolResult, ToolStatus
except ImportError:
    try:
        from tools.base import Tool, ToolResult, ToolStatus
    except ImportError:
        from agents.DotaHelperAgent.tools.base import Tool, ToolResult, ToolStatus


@dataclass
class ToolCall:
    """工具调用记录"""
    tool_name: str
    parameters: Dict[str, Any]
    result: Optional[ToolResult] = None
    timestamp: float = field(default_factory=time.time)
    execution_time: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "result": self.result.to_dict() if self.result else None,
            "timestamp": self.timestamp,
            "execution_time": self.execution_time
        }


class ToolRegistry:
    """工具注册表

    管理 Agent 可用的所有 Tools，支持：
    - 按名称、类别检索
    - 工具调用历史记录
    - 工具执行统计
    - 转换为 OpenAI Function Calling 格式
    - 工具链编排
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._tools_by_category: Dict[str, List[Tool]] = {}
        self._call_history: List[ToolCall] = []
        self._stats: Dict[str, Dict[str, Any]] = {}

    def register(self, tool: Tool) -> None:
        """注册 Tool"""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")

        self._tools[tool.name] = tool

        if tool.category not in self._tools_by_category:
            self._tools_by_category[tool.category] = []
        self._tools_by_category[tool.category].append(tool)
        
        # 初始化工具统计
        self._stats[tool.name] = {
            "call_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "total_execution_time": 0.0,
            "last_called": None
        }

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
                status=ToolStatus.FAILURE,
                data=None,
                error=f"Tool '{tool_name}' not found"
            )

        # 记录调用开始时间
        start_time = time.time()
        
        result = tool.execute(**kwargs)
        
        # 计算执行时间
        execution_time = time.time() - start_time
        
        # 记录调用历史
        call_record = ToolCall(
            tool_name=tool_name,
            parameters=kwargs,
            result=result,
            execution_time=execution_time
        )
        self._call_history.append(call_record)
        
        # 更新统计
        self._update_stats(tool_name, result, execution_time)

        return result
    
    def execute_chain(self, tool_chain: List[Dict[str, Any]]) -> List[ToolResult]:
        """执行工具链
        
        Args:
            tool_chain: 工具链配置，每项包含 tool_name 和 parameters
            
        Returns:
            工具执行结果列表
        """
        results = []
        for step in tool_chain:
            tool_name = step.get('tool_name')
            parameters = step.get('parameters', {})
            
            if not tool_name:
                continue
                
            result = self.execute(tool_name, **parameters)
            results.append(result)
            
            # 如果某一步失败，可以选择是否继续
            if not result.is_success():
                break
                
        return results

    def get_call_history(self, limit: int = 10) -> List[ToolCall]:
        """获取调用历史"""
        return self._call_history[-limit:]

    def clear_history(self) -> None:
        """清空调用历史"""
        self._call_history.clear()

    def get_stats(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """获取工具统计信息
        
        Args:
            tool_name: 工具名称，如果为 None 则返回所有工具统计
            
        Returns:
            统计信息字典
        """
        if tool_name:
            return self._stats.get(tool_name, {})
        return self._stats

    def get_success_rate(self, tool_name: str) -> float:
        """获取工具成功率"""
        stats = self._stats.get(tool_name, {})
        total = stats.get('call_count', 0)
        success = stats.get('success_count', 0)
        return success / total if total > 0 else 0.0

    def to_openai_format(self, tool_names: Optional[List[str]] = None) -> List[Dict]:
        """将工具转换为 OpenAI Function Calling 格式
        
        Args:
            tool_names: 要转换的工具名称列表，如果为 None 则转换所有工具
            
        Returns:
            OpenAI Function Calling 格式的工具列表
        """
        tools_to_convert = []
        if tool_names:
            for name in tool_names:
                tool = self.get(name)
                if tool:
                    tools_to_convert.append(tool)
        else:
            tools_to_convert = list(self._tools.values())

        return [self._tool_to_openai(tool) for tool in tools_to_convert]

    def _tool_to_openai(self, tool: Tool) -> Dict:
        """将单个工具转换为 OpenAI 格式"""
        schema = tool.get_schema()
        return {
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema["description"],
                "parameters": schema["parameters"]
            }
        }

    def _update_stats(self, tool_name: str, result: ToolResult, execution_time: float) -> None:
        """更新工具统计信息"""
        if tool_name not in self._stats:
            self._stats[tool_name] = {
                "call_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "total_execution_time": 0.0,
                "last_called": None
            }

        stats = self._stats[tool_name]
        stats["call_count"] += 1
        stats["total_execution_time"] += execution_time
        stats["last_called"] = time.time()

        if result.status == ToolStatus.SUCCESS:
            stats["success_count"] += 1
        else:
            stats["failure_count"] += 1

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
    
    def __iter__(self):
        """迭代所有工具"""
        return iter(self._tools.values())