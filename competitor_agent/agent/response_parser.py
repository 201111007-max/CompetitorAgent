"""LLM 输出解析器 — 提取 Thought/Action/Final Answer 结构化信息

从 dota_helper/agent/response_parser.py 通用化迁移（去掉 Dota 领域依赖）。
解析策略：
- 优先匹配 <action>tool_name(args)</action> 结构化标签
- 回退匹配 Action: tool_name + Args: {...} 行模式
- 识别 Final Answer: 或 <final_answer> 作为终止信号
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from competitor_agent.agent.tool_dispatcher import ToolArgumentError
from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.response_parser")


class StepType(Enum):
    """ReAct 步骤类型"""
    THOUGHT = "thought"
    ACTION = "action"
    FINAL_ANSWER = "final_answer"


@dataclass
class ReActStep:
    """ReAct 推理步骤"""

    step_type: StepType
    thought: str = ""
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    args_error: str = ""  # 参数 JSON 解析失败原因（非空表示解析失败，供回灌）
    final_answer: str = ""
    raw_text: str = ""


class ResponseParser:
    """解析 LLM 输出，提取结构化 ReAct 信息"""

    _ACTION_TAG_PATTERN = re.compile(r"<action>\s*(\w+)\s*\((.*?)\)\s*</action>", re.DOTALL)
    _ACTION_LINE_PATTERN = re.compile(r"Action:\s*(\w+)", re.IGNORECASE)
    _ARGS_LINE_PATTERN = re.compile(r"Args:\s*(\{.*\})", re.DOTALL)
    _FINAL_ANSWER_LINE_PATTERN = re.compile(r"Final Answer:\s*(.*)", re.DOTALL)
    _FINAL_ANSWER_TAG_PATTERN = re.compile(r"<final_answer>\s*(.*?)\s*</final_answer>", re.DOTALL)
    _THOUGHT_PATTERN = re.compile(r"Thought:\s*(.*?)(?=\n(?:Action|Final Answer)|$)", re.DOTALL)

    def parse(self, llm_output: str) -> ReActStep:
        """按优先级：Final Answer → Action 标签 → Action 行模式 → 纯 Thought"""
        final_answer = self.extract_final_answer(llm_output)
        if final_answer is not None:
            return ReActStep(
                step_type=StepType.FINAL_ANSWER,
                final_answer=final_answer,
                raw_text=llm_output,
            )

        action_result = self.extract_action(llm_output)
        if action_result is not None:
            tool_name, tool_args, args_error = action_result
            return ReActStep(
                step_type=StepType.ACTION,
                thought=self._extract_thought(llm_output),
                tool_name=tool_name,
                tool_args=tool_args,
                args_error=args_error,
                raw_text=llm_output,
            )

        return ReActStep(
            step_type=StepType.THOUGHT,
            thought=self._extract_thought(llm_output) or llm_output,
            raw_text=llm_output,
        )

    def extract_action(self, text: str) -> tuple[str, dict[str, Any], str] | None:
        """返回 (tool_name, tool_args, args_error)；解析失败时 args_error 非空、args 为空 dict。"""
        tag_match = self._ACTION_TAG_PATTERN.search(text)
        if tag_match:
            return self._action_args(tag_match.group(1), tag_match.group(2))

        line_match = self._ACTION_LINE_PATTERN.search(text)
        if line_match:
            args_match = self._ARGS_LINE_PATTERN.search(text)
            if args_match:
                return self._action_args(line_match.group(1), args_match.group(1))
            return (line_match.group(1), {}, "")  # 无 Args: 兼容既有行为
        return None

    @staticmethod
    def _action_args(tool_name: str, args_str: str) -> tuple[str, dict[str, Any], str]:
        try:
            return (tool_name, ResponseParser._parse_json_args(args_str), "")
        except ToolArgumentError as exc:
            return (tool_name, {}, str(exc))

    def extract_final_answer(self, text: str) -> str | None:
        line_match = self._FINAL_ANSWER_LINE_PATTERN.search(text)
        if line_match:
            return line_match.group(1).strip()
        tag_match = self._FINAL_ANSWER_TAG_PATTERN.search(text)
        if tag_match:
            return tag_match.group(1).strip()
        return None

    def _extract_thought(self, text: str) -> str:
        match = self._THOUGHT_PATTERN.search(text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _parse_json_args(args_str: str) -> dict[str, Any]:
        """解析参数 JSON；失败/非对象抛 ToolArgumentError（设计文档 38，不再静默 {}）。"""
        try:
            result = json.loads(args_str)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ToolArgumentError(f"JSON 解析失败: {exc}") from exc
        if not isinstance(result, dict):
            raise ToolArgumentError(f"JSON 解析失败: 期望对象，实际 {type(result).__name__}")
        return result