"""ReAct 系统提示词构建 — 53 工具描述注入 + Skill 懒加载

构建完整的系统提示词，包含：
1. 角色定义：Dota 2 赛后复盘分析助手
2. 工具描述：53 个 MCP 工具的功能说明和参数 schema
3. 输出格式：ReAct 推理链格式指引（Thought → Action → Observation → Final Answer）
4. Skill 懒加载：可选的已沉淀技能提示
"""
from typing import Any, Dict, List, Optional

from dota_helper.observability.logger import get_logger

logger = get_logger("agent.prompts.react_system")


# ── 系统提示词模板 ──

_SYSTEM_ROLE_TEMPLATE = """你是 Dota 2 赛后复盘分析助手（Dota Helper Agent），具备专业的 Dota 2 游戏分析能力。

你可以通过调用工具来获取比赛数据、英雄信息、玩家统计等，并为用户提供深入的分析和建议。

## 可用工具

{tool_descriptions}

## 推理格式

你必须严格按照 ReAct（Thought → Action → Observation）格式进行推理：

1. **Thought**: 分析当前情况，决定下一步行动
   格式：Thought: 你的思考过程

2. **Action**: 选择并调用合适的工具
   格式：Action: tool_name
         Args: {{"param1": "value1", "param2": "value2"}}

   或使用结构化标签：
   <action>tool_name({{"param1": "value1"}})</action>

3. **Observation**: 工具返回的结果（系统自动填入）

4. **Final Answer**: 当你获得足够信息后，给出最终分析结果
   格式：Final Answer: 你的最终分析和建议

## 分析原则

- 每次只调用一个工具，等待 Observation 后再决定下一步
- 优先获取关键数据（比赛详情、玩家数据），再做深度分析
- 如果数据不完整，可以多次调用不同工具补充信息
- 最终回答需要包含具体的数据支撑和可操作的建议
- 使用中文回复用户"""

_SKILL_INJECTION_TEMPLATE = """

## 已沉淀技能

以下是历史复盘中沉淀的分析技能，可以按需参考：

{skill_descriptions}"""


class ReactSystemPrompt:
    """构建 ReAct 系统提示词

    将工具描述、技能信息等动态内容注入系统提示词模板，
    生成完整的 LLM 系统消息。
    """

    def __init__(self, custom_role_template: Optional[str] = None) -> None:
        """初始化系统提示词构建器

        Args:
            custom_role_template: 自定义角色模板（覆盖默认模板）
        """
        self._role_template = custom_role_template or _SYSTEM_ROLE_TEMPLATE
        logger.debug("系统提示词构建器初始化")

    def build(
        self,
        tool_descriptions: str,
        skills: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """构建完整系统提示词

        组合角色定义 + 工具描述 + 输出格式 + Skill 懒加载提示。

        Args:
            tool_descriptions: 格式化的工具描述文本（来自 ToolDispatcher）
            skills: 可选的已沉淀技能列表，每项包含 name/description/trigger_hint

        Returns:
            str: 完整的系统提示词
        """
        # 基础提示词：角色 + 工具描述 + 输出格式
        prompt = self._role_template.format(
            tool_descriptions=tool_descriptions,
        )

        # 可选：注入已沉淀技能
        if skills:
            skill_descriptions = self._format_skills(skills)
            prompt += _SKILL_INJECTION_TEMPLATE.format(
                skill_descriptions=skill_descriptions,
            )

        logger.debug(
            "系统提示词构建完成: len=%d, skills=%d",
            len(prompt),
            len(skills) if skills else 0,
        )
        return prompt

    def _format_skills(self, skills: List[Dict[str, Any]]) -> str:
        """格式化技能描述

        Args:
            skills: 技能列表

        Returns:
            str: 格式化的技能描述文本
        """
        descriptions = []
        for skill in skills:
            name = skill.get("name", "unknown")
            desc = skill.get("description", "无描述")
            trigger = skill.get("trigger_hint", "")

            skill_str = f"- **{name}**: {desc}"
            if trigger:
                skill_str += f"\n  触发条件：{trigger}"
            descriptions.append(skill_str)

        return "\n".join(descriptions)
