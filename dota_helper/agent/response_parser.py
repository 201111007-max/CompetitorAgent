"""LLM 输出解析器 — 提取 Thought/Action/Final Answer 结构化信息

解析策略：
- 优先匹配 <action>tool_name(args)</action> 结构化标签
- 回退匹配 Action: tool_name + Args: {...} 行模式
- 识别 Final Answer: 或 <final_answer> 作为终止信号
"""
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from dota_helper.observability.logger import get_logger

logger = get_logger("agent.response_parser")


class StepType(Enum):
    """ReAct 步骤类型"""
    THOUGHT = "thought"
    ACTION = "action"
    FINAL_ANSWER = "final_answer"


@dataclass
class ReActStep:
    """ReAct 推理步骤

    Attributes:
        step_type: 步骤类型（Thought/Action/FinalAnswer）
        thought: 思考内容
        tool_name: 工具名称（仅 ACTION 类型有值）
        tool_args: 工具参数（仅 ACTION 类型有值）
        final_answer: 最终回答（仅 FINAL_ANSWER 类型有值）
        raw_text: 原始 LLM 输出文本
    """
    step_type: StepType
    thought: str = ""
    tool_name: str = ""
    tool_args: Dict[str, Any] = field(default_factory=dict)
    final_answer: str = ""
    raw_text: str = ""


class ResponseParser:
    """解析 LLM 输出，提取结构化 ReAct 信息

    按优先级尝试三种解析模式：
    1. 结构化标签模式：<action>tool_name(args)</action>
    2. 行模式：Action: tool_name \\n Args: {...}
    3. 终止信号：Final Answer: ... 或 <final_answer>...</final_answer>
    """

    # ── 正则模式 ──

    # 结构化标签：<action>tool_name({"key": "value"})</action>
    _ACTION_TAG_PATTERN = re.compile(
        r"<action>\s*(\w+)\s*\((.*?)\)\s*</action>",
        re.DOTALL,
    )

    # 行模式：Action: tool_name
    _ACTION_LINE_PATTERN = re.compile(
        r"Action:\s*(\w+)",
        re.IGNORECASE,
    )

    # 行模式：Args: {"key": "value"}
    _ARGS_LINE_PATTERN = re.compile(
        r"Args:\s*(\{.*\})",
        re.DOTALL,
    )

    # 终止信号：Final Answer: ...
    _FINAL_ANSWER_LINE_PATTERN = re.compile(
        r"Final Answer:\s*(.*)",
        re.DOTALL,
    )

    # 终止信号：<final_answer>...</final_answer>
    _FINAL_ANSWER_TAG_PATTERN = re.compile(
        r"<final_answer>\s*(.*?)\s*</final_answer>",
        re.DOTALL,
    )

    # Thought 提取：Thought: ...
    _THOUGHT_PATTERN = re.compile(
        r"Thought:\s*(.*?)(?=\n(?:Action|Final Answer)|$)",
        re.DOTALL,
    )

    def parse(self, llm_output: str) -> ReActStep:
        """解析 LLM 输出为 Thought/Action/FinalAnswer

        按优先级依次尝试：Final Answer → Action 标签 → Action 行模式 → 纯 Thought

        Args:
            llm_output: LLM 原始输出文本

        Returns:
            ReActStep: 解析后的结构化步骤
        """
        # 1. 检查 Final Answer
        final_answer = self.extract_final_answer(llm_output)
        if final_answer is not None:
            logger.debug("解析为 Final Answer: %s", final_answer[:80])
            return ReActStep(
                step_type=StepType.FINAL_ANSWER,
                final_answer=final_answer,
                raw_text=llm_output,
            )

        # 2. 检查 Action（结构化标签优先）
        action_result = self.extract_action(llm_output)
        if action_result is not None:
            tool_name, tool_args = action_result
            thought = self._extract_thought(llm_output)
            logger.debug("解析为 Action: tool=%s, args=%s", tool_name, tool_args)
            return ReActStep(
                step_type=StepType.ACTION,
                thought=thought,
                tool_name=tool_name,
                tool_args=tool_args,
                raw_text=llm_output,
            )

        # 3. 纯 Thought（LLM 未产出 Action 或 Final Answer）
        thought = self._extract_thought(llm_output) or llm_output
        logger.debug("解析为 Thought: %s", thought[:80])
        return ReActStep(
            step_type=StepType.THOUGHT,
            thought=thought,
            raw_text=llm_output,
        )

    def extract_action(self, text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """提取 Action（工具名 + 参数）

        优先匹配结构化标签，回退匹配行模式。

        Args:
            text: LLM 输出文本

        Returns:
            Optional[Tuple[str, Dict[str, Any]]]: (tool_name, tool_args) 或 None
        """
        # 尝试结构化标签
        tag_match = self._ACTION_TAG_PATTERN.search(text)
        if tag_match:
            tool_name = tag_match.group(1)
            tool_args = self._parse_json_args(tag_match.group(2))
            return (tool_name, tool_args)

        # 回退到行模式
        line_match = self._ACTION_LINE_PATTERN.search(text)
        if line_match:
            tool_name = line_match.group(1)
            # 查找 Args 行
            args_match = self._ARGS_LINE_PATTERN.search(text)
            if args_match:
                tool_args = self._parse_json_args(args_match.group(1))
            else:
                tool_args = {}
            return (tool_name, tool_args)

        return None

    def extract_final_answer(self, text: str) -> Optional[str]:
        """提取 Final Answer

        优先匹配 Final Answer: 行模式，回退匹配 <final_answer> 标签。

        Args:
            text: LLM 输出文本

        Returns:
            Optional[str]: 最终回答文本或 None
        """
        # 行模式
        line_match = self._FINAL_ANSWER_LINE_PATTERN.search(text)
        if line_match:
            return line_match.group(1).strip()

        # 标签模式
        tag_match = self._FINAL_ANSWER_TAG_PATTERN.search(text)
        if tag_match:
            return tag_match.group(1).strip()

        return None

    def _extract_thought(self, text: str) -> str:
        """提取 Thought 文本

        Args:
            text: LLM 输出文本

        Returns:
            str: 思考内容
        """
        match = self._THOUGHT_PATTERN.search(text)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _parse_json_args(args_str: str) -> Dict[str, Any]:
        """解析 JSON 格式的参数字符串

        Args:
            args_str: JSON 格式参数字符串

        Returns:
            Dict[str, Any]: 解析后的参数字典，解析失败返回空字典
        """
        try:
            result = json.loads(args_str)
            if isinstance(result, dict):
                return result
            return {}
        except (json.JSONDecodeError, TypeError):
            logger.debug("JSON 参数解析失败: %s", args_str[:80])
            return {}
