"""LLM Tool Selector - 基于 LLM 的智能工具选择器

使用大语言模型理解用户查询意图，自主选择合适的工具并提取参数
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from utils.llm_client import LLMClient
from core.tool_registry import ToolRegistry


@dataclass
class ToolCall:
    """单个工具调用"""
    tool_name: str
    parameters: Dict[str, Any]


@dataclass
class ToolCallPlan:
    """工具调用计划"""
    tools: List[ToolCall]
    reasoning: str


class LLMToolSelector:
    """LLM 工具选择器

    使用 LLM 理解用户查询，智能选择合适的工具并提取参数
    """

    TOOL_SELECTION_PROMPT = """你是一个 Dota 2 游戏助手，负责分析用户查询并选择合适的工具来回答问题。

## 可用工具

{tools_description}

## 当前上下文

{context_info}

## 对话历史

{conversation_history}

## 用户查询

{query}

## 任务要求

请分析用户查询，完成以下任务：

1. 理解用户的真实意图（考虑对话历史）
2. 选择合适的工具（可以选多个，按执行顺序排列）
3. 从查询和上下文中提取每个工具需要的参数

## 返回格式

请严格按照以下 JSON 格式返回：

```json
{{
    "reasoning": "选择这些工具的原因和执行策略",
    "tools": [
        {{
            "name": "工具名称",
            "parameters": {{
                "参数名1": "参数值1",
                "参数名2": ["值1", "值2"]
            }}
        }}
    ]
}}
```

## 注意事项

1. 只选择必要的工具，不要过度调用
2. 参数值必须从用户查询和上下文中提取，不要编造
3. 如果某个参数无法提取，可以设置为 null 或使用默认值
4. 工具按顺序执行，请合理安排顺序
5. 必须返回有效的 JSON，不要添加额外内容
6. 如果有对话历史，请考虑上下文连贯性"""

    def __init__(self, llm_client: LLMClient, tool_registry: ToolRegistry):
        """初始化 LLM 工具选择器

        Args:
            llm_client: LLM 客户端实例
            tool_registry: 工具注册表
        """
        self.llm = llm_client
        self.registry = tool_registry

    def select_tools(self, query: str, context: Optional[Dict[str, Any]] = None) -> ToolCallPlan:
        """智能选择工具

        Args:
            query: 用户查询
            context: 上下文信息（可选）

        Returns:
            ToolCallPlan: 工具调用计划

        Raises:
            Exception: LLM 调用失败或解析失败
        """
        print(f"\n[LLMToolSelector] 开始工具选择")
        print(f"[LLMToolSelector] Query: {query}")
        print(f"[LLMToolSelector] Context: {context}")

        # 1. 获取可用工具描述
        tools_desc = self._format_tools_description()
        print(f"[LLMToolSelector] 可用工具数量: {len(self.registry.list_tools())}")
        print(f"[LLMToolSelector] 工具列表: {self.registry.list_tools()}")

        # 2. 构造上下文信息
        context_info = self._format_context(context)
        print(f"[LLMToolSelector] 上下文信息: {context_info}")

        # 3. 构造对话历史
        conversation_history = self._format_conversation_history(context)
        print(f"[LLMToolSelector] 对话历史: {'有' if conversation_history != '无对话历史' else '无'}")

        # 4. 构造 Prompt
        prompt = self.TOOL_SELECTION_PROMPT.format(
            tools_description=tools_desc,
            context_info=context_info,
            conversation_history=conversation_history,
            query=query
        )

        # 5. 调用 LLM
        print(f"[LLMToolSelector] 调用 LLM 进行工具选择...")
        response = self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1024
        )

        # 6. 检查 LLM 响应
        if "error" in response:
            error_msg = response.get("error", "未知错误")
            print(f"[LLMToolSelector] LLM 返回错误: {error_msg}")
            raise Exception(f"LLM 工具选择失败：{error_msg}")

        # 7. 解析 LLM 返回内容
        try:
            content = response['choices'][0]['message']['content']
            print(f"[LLMToolSelector] LLM 原始响应:\n{content}")
        except (KeyError, IndexError) as e:
            print(f"[LLMToolSelector] LLM 响应格式异常: {e}")
            raise Exception(f"LLM 响应格式异常：{e}")

        # 8. 解析 JSON
        plan = self._parse_plan(content)
        print(f"[LLMToolSelector] 解析后的工具计划:")
        print(f"[LLMToolSelector]   Reasoning: {plan.reasoning}")
        print(f"[LLMToolSelector]   Tools: {[t.tool_name for t in plan.tools]}")
        for tool_call in plan.tools:
            print(f"[LLMToolSelector]   - {tool_call.tool_name}: {tool_call.parameters}")

        # 9. 验证工具计划
        self._validate_plan(plan)
        print(f"[LLMToolSelector] 工具计划验证通过")

        return plan

    def _format_tools_description(self) -> str:
        """格式化工具描述"""
        tools = self.registry.list_tools()
        if not tools:
            return "无可用工具"

        desc_parts = []
        for tool_name in tools:
            tool = self.registry.get(tool_name)
            if tool:
                schema = tool.get_schema()
                desc_parts.append(f"### {tool_name}\n")
                desc_parts.append(f"描述：{schema['description']}\n")
                desc_parts.append(f"类别：{schema.get('category', 'general')}\n")

                # 参数信息
                params = schema.get('parameters', {}).get('properties', {})
                if params:
                    desc_parts.append("参数：")
                    for param_name, param_info in params.items():
                        param_type = param_info.get('type', 'any')
                        desc_parts.append(f"  - {param_name} ({param_type})")
                    desc_parts.append("")

                # 示例
                examples = schema.get('examples', [])
                if examples:
                    desc_parts.append("示例：")
                    for example in examples:
                        desc_parts.append(f"  - {example}")
                    desc_parts.append("")

        return "\n".join(desc_parts)

    def _format_context(self, context: Optional[Dict[str, Any]]) -> str:
        """格式化上下文信息"""
        if not context:
            return "无额外上下文"

        context_parts = []
        for key, value in context.items():
            if key == 'memory_context':
                context_parts.append(f"历史对话记忆：{value}")
            elif key == 'conversation_history':
                continue
            elif key in ['our_heroes', 'enemy_heroes', 'current_heroes', 'current_topic', 'inferred_intent', 'entities', 'entity_history', 'turn_count']:
                context_parts.append(f"{key}: {value}")
            else:
                context_parts.append(f"{key}: {value}")

        return "\n".join(context_parts) if context_parts else "无额外上下文"

    def _format_conversation_history(self, context: Optional[Dict[str, Any]]) -> str:
        """格式化对话历史"""
        if not context or 'conversation_history' not in context:
            return "无对话历史"

        history = context['conversation_history']
        if not history or len(history) == 0:
            return "无对话历史"

        history_parts = []
        for msg in history[-10:]:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            role_label = "用户" if role == "user" else "助手"
            history_parts.append(f"{role_label}: {content}")

        return "\n".join(history_parts) if history_parts else "无对话历史"

    def _parse_plan(self, content: str) -> ToolCallPlan:
        """解析 LLM 返回的工具计划

        Args:
            content: LLM 返回的文本内容

        Returns:
            ToolCallPlan: 工具调用计划

        Raises:
            Exception: 解析失败
        """
        # 尝试提取 JSON（可能包含在 markdown 代码块中）
        json_str = self._extract_json(content)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"[LLMToolSelector] JSON 解析失败: {e}")
            print(f"[LLMToolSelector] 原始内容: {json_str}")
            raise Exception(f"工具计划 JSON 解析失败：{e}")

        # 验证必要字段
        if 'tools' not in data:
            raise Exception("工具计划缺少 'tools' 字段")

        if 'reasoning' not in data:
            raise Exception("工具计划缺少 'reasoning' 字段")

        # 解析工具调用
        tool_calls = []
        for tool_data in data['tools']:
            if 'name' not in tool_data:
                raise Exception(f"工具数据缺少 'name' 字段: {tool_data}")

            tool_call = ToolCall(
                tool_name=tool_data['name'],
                parameters=tool_data.get('parameters', {})
            )
            tool_calls.append(tool_call)

        return ToolCallPlan(
            tools=tool_calls,
            reasoning=data['reasoning']
        )

    def _extract_json(self, content: str) -> str:
        """从内容中提取 JSON 字符串

        支持从 markdown 代码块中提取
        """
        # 尝试提取 markdown 代码块中的 JSON
        import re

        # 匹配 ```json ... ``` 或 ``` ... ```
        pattern = r'```(?:json)?\s*\n?([\s\S]*?)\n?```'
        match = re.search(pattern, content)

        if match:
            return match.group(1).strip()

        # 如果没有代码块，尝试直接解析整个内容
        return content.strip()

    def _validate_plan(self, plan: ToolCallPlan) -> None:
        """验证工具计划

        Args:
            plan: 工具调用计划

        Raises:
            Exception: 验证失败
        """
        if not plan.tools:
            raise Exception("工具计划为空")

        available_tools = set(self.registry.list_tools())

        for tool_call in plan.tools:
            # 检查工具是否存在
            if tool_call.tool_name not in available_tools:
                raise Exception(
                    f"工具 '{tool_call.tool_name}' 不存在，"
                    f"可用工具: {', '.join(available_tools)}"
                )

            # 检查参数是否为空字典（可选，有些工具可能不需要参数）
            if not isinstance(tool_call.parameters, dict):
                raise Exception(
                    f"工具 '{tool_call.tool_name}' 的参数格式错误，"
                    f"应为字典类型，实际为: {type(tool_call.parameters)}"
                )

        print(f"[LLMToolSelector] 验证通过: {len(plan.tools)} 个工具均有效")
