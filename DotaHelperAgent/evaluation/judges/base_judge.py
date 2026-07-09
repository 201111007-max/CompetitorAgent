"""基础 Judge 抽象类

所有 Judge 实现必须继承此基类。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import logging
import json
import re

from ..base import (
    BaseEvaluator,
    EvaluationContext,
    EvaluationResult,
    EvaluationStatus,
    ScoreDimension,
)

logger = logging.getLogger(__name__)


class BaseJudge(BaseEvaluator, ABC):
    """Judge 抽象基类

    Attributes:
        llm_adapter: LLM 适配器（封装真实 LLMClient 或 Mock）
        prompt_template: Judge Prompt 模板
        temperature: 采样温度（默认 0.0 降低噪声）
        n_samples: 多次采样次数（取平均）
    """

    def __init__(
        self,
        llm_adapter: Any,
        prompt_template: Optional[Dict] = None,
        temperature: float = 0.0,
        n_samples: int = 3,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.llm_adapter = llm_adapter
        self.prompt_template = prompt_template or {}
        self.temperature = temperature
        self.n_samples = n_samples

    @abstractmethod
    def build_prompt(
        self,
        context: EvaluationContext,
    ) -> str:
        """构造 Judge Prompt"""
        pass

    @abstractmethod
    def parse_response(
        self,
        response: str,
    ) -> Dict[ScoreDimension, float]:
        """解析 Judge 响应为维度评分"""
        pass

    def evaluate(
        self,
        context: EvaluationContext,
    ) -> EvaluationResult:
        """执行 Judge 评估（同步，多次采样取平均）"""
        prompt = self.build_prompt(context)

        # 多次采样
        samples: List[Dict[ScoreDimension, float]] = []
        reasonings: List[str] = []
        for i in range(self.n_samples):
            response = self.llm_adapter.generate(
                prompt,
                temperature=self.temperature,
            )
            parsed = self.parse_response(response)
            samples.append(parsed)
            reasonings.append(response)

        # 平均化
        avg_scores = self._average_samples(samples)

        return EvaluationResult(
            case_id=context.case_id,
            evaluator_name=self.name,
            status=EvaluationStatus.COMPLETED,
            dimension_scores=avg_scores,
            confidence=min(1.0, len(samples) / self.n_samples),
            reasoning=reasonings[0] if reasonings else "",
            metadata={
                "n_samples": len(samples),
                "is_mock": self.llm_adapter.is_mock()
                if hasattr(self.llm_adapter, "is_mock")
                else False,
            },
        )

    def _average_samples(
        self,
        samples: List[Dict[ScoreDimension, float]],
    ) -> Dict[ScoreDimension, float]:
        """对多次采样结果取平均"""
        if not samples:
            return {}
        all_dims = set()
        for s in samples:
            all_dims.update(s.keys())
        return {
            dim: round(sum(s.get(dim, 0.0) for s in samples) / len(samples), 2)
            for dim in all_dims
        }

    @staticmethod
    def extract_json(response: str) -> str:
        """从响应中提取 JSON 字符串（处理 markdown 代码块）"""
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
        if json_match:
            return json_match.group(1)
        json_match = re.search(r"\{.*\}", response, re.DOTALL)
        return json_match.group(0) if json_match else response
