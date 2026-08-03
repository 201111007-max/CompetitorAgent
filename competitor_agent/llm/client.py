"""LLM Client 抽象：驱动维度分析，LLM 不可用时降级

M1 提供：
- LLMClient：基于 openai SDK 的调用封装（parse/summarize 语义化方法）
- 可注入 mock，供测试与规则降级
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from competitor_agent.interfaces.exceptions import LLMUnavailableError

logger = logging.getLogger("competitor_agent.llm.client")


class LLMClient:
    """统一 LLM 调用封装（可注入 callable 便于测试）"""

    def __init__(
        self,
        call_func: Callable[..., str] | None = None,
        model: str = "deepseek-v4-flash",
    ) -> None:
        # call_func: (messages, **kwargs) -> str；默认走 openai SDK（惰性导入）
        self._call = call_func
        self._model = model

    def complete(self, messages: list[dict[str, str]]) -> str:
        """最通用：返回原始文本"""
        if self._call is not None:
            return self._call(messages=messages, model=self._model)

        try:
            from openai import OpenAI  # 惰性导入，避免无 key 环境失败
        except ImportError as exc:
            raise LLMUnavailableError("openai SDK 未安装") from exc

        client = OpenAI()
        response = client.chat.completions.create(model=self._model, messages=messages)
        return response.choices[0].message.content or ""

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """要求模型输出 JSON，解析失败抛 LLMUnavailableError"""
        text = self.complete(messages)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMUnavailableError(f"LLM 返回非 JSON: {exc}") from exc