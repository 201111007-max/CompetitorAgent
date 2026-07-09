"""7 维评分 Judge

实现 7 维评分量表（正确性/完整性/相关性/工具选择/效率/鲁棒性/个性化）。
"""

import json
import logging
from typing import Any, Dict, Optional

from ..base import EvaluationContext, EvaluationStatus, ScoreDimension
from .base_judge import BaseJudge

logger = logging.getLogger(__name__)

# 7 维评分通用 Prompt 模板
DEFAULT_SEVEN_DIM_PROMPT = {
    "system": (
        "你是一名专业的 AI 助手输出质量评估专家。"
        "请基于以下 7 个维度评估输出质量（每维 1-5 分）：\n"
        "1. 正确性（25%）：答案是否准确、是否符合事实\n"
        "2. 完整性（15%）：是否覆盖所有要点\n"
        "3. 相关性（15%）：是否切题、避免无关内容\n"
        "4. 工具选择（15%）：使用的工具是否合适\n"
        "5. 效率（10%）：步骤是否精简、路径是否最优\n"
        "6. 鲁棒性（10%）：对异常输入的容错\n"
        "7. 个性化（10%）：是否贴合用户风格"
    ),
    "template": (
        "## 输入\n{input}\n\n"
        "## 期望输出\n{expected}\n\n"
        "## 实际输出\n{actual}\n\n"
        "## 评估\n请按 7 维度评分（1-5），并给出总分（加权平均）和简要理由。\n\n"
        "输出 JSON 格式：\n"
        "{{\n"
        '  "correctness": 1-5,\n'
        '  "completeness": 1-5,\n'
        '  "relevance": 1-5,\n'
        '  "tool_selection": 1-5,\n'
        '  "efficiency": 1-5,\n'
        '  "robustness": 1-5,\n'
        '  "personalization": 1-5,\n'
        '  "total_score": 加权平均,\n'
        '  "reasoning": "评分理由"\n'
        "}}"
    ),
}


class MultiDimensionalJudge(BaseJudge):
    """7 维评分 Judge

    Attributes:
        module_name: 对应的 Skill/SubAgent 模块名（用于加载专属 Prompt）
    """

    def __init__(
        self,
        llm_adapter: Any,
        module_name: Optional[str] = None,
        prompt_overrides: Optional[Dict] = None,
        n_samples: int = 1,  # 评测场景默认 1 次（成本考量）
        **kwargs,
    ):
        super().__init__(
            name=f"multi_dimensional_judge_{module_name or 'default'}",
            version="1.0.0",
            description="7 维评分 Judge",
            llm_adapter=llm_adapter,
            n_samples=n_samples,
            **kwargs,
        )
        self.module_name = module_name
        self.prompt_overrides = prompt_overrides or {}
        # 如果没有提供 template，使用默认
        if not self.prompt_template:
            self.prompt_template = DEFAULT_SEVEN_DIM_PROMPT

    def build_prompt(self, context: EvaluationContext) -> str:
        """构造 Judge Prompt"""
        template = self.prompt_overrides.get("template") or self.prompt_template.get(
            "template", DEFAULT_SEVEN_DIM_PROMPT["template"]
        )
        system = self.prompt_overrides.get("system") or self.prompt_template.get(
            "system", DEFAULT_SEVEN_DIM_PROMPT["system"]
        )

        # 提取期望关键点
        expected = context.expected_output or {}
        if isinstance(expected, dict):
            expected_points = "\n".join(f"- {p}" for p in expected.get("key_points", []))
        else:
            expected_points = str(expected)

        user_prompt = template.format(
            input=context.input_data,
            expected=expected_points,
            actual=context.actual_output,
        )

        # 合并 system + user
        return f"{system}\n\n{user_prompt}"

    def parse_response(self, response: str) -> Dict[ScoreDimension, float]:
        """解析 Judge 响应"""
        json_str = self.extract_json(response)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON: {json_str[:200]}")
            return {dim: 3.0 for dim in ScoreDimension}

        # 映射到 ScoreDimension 枚举
        dimension_map = {
            "correctness": ScoreDimension.CORRECTNESS,
            "completeness": ScoreDimension.COMPLETENESS,
            "relevance": ScoreDimension.RELEVANCE,
            "tool_selection": ScoreDimension.TOOL_SELECTION,
            "efficiency": ScoreDimension.EFFICIENCY,
            "robustness": ScoreDimension.ROBUSTNESS,
            "personalization": ScoreDimension.PERSONALIZATION,
        }

        scores = {}
        for key, dim in dimension_map.items():
            if key in data:
                try:
                    score = float(data[key])
                    scores[dim] = max(1.0, min(5.0, score))
                except (ValueError, TypeError):
                    scores[dim] = 3.0
        return scores
