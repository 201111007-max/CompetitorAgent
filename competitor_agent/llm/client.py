"""LLM Client 抽象：驱动维度分析，LLM 不可用时降级

M1 提供：
- LLMClient：基于 openai SDK 的调用封装（parse/summarize 语义化方法）
- 可注入 mock，供测试与规则降级

凭据与端点通过环境变量控制（不明文落码）：
- OPENAI_API_KEY：API Key（兼容 DEEPSEEK_API_KEY / LLM_API_KEY 别名）
- OPENAI_BASE_URL：OpenAI 兼容端点（DeepSeek 等），默认官方 OpenAI
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable

from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.observability.logger import emit_session_event

logger = logging.getLogger("competitor_agent.llm.client")

# 脱敏 LLM 调用日志的粗略计价（美元/千 token），仅用于可观测性展示
_PRICING_PER_1K = {"input": 0.0003, "output": 0.0006}  # DeepSeek 量级近似


def _estimate_tokens(texts: list[str]) -> int:
    return sum(len(t) // 4 for t in texts)

# 兼容别名链：OPENAI_API_KEY > DEEPSEEK_API_KEY > LLM_API_KEY
_API_KEY_ENVS = ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "LLM_API_KEY")
_BASE_URL_ENV = "OPENAI_BASE_URL"


class LLMClient:
    """统一 LLM 调用封装（可注入 callable 便于测试）"""

    def __init__(
        self,
        call_func: Callable[..., str] | None = None,
        model: str = "deepseek-chat",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        # call_func: (messages, **kwargs) -> str；默认走 openai SDK（惰性导入）
        self._call = call_func
        self._model = model
        # 显式传入优先，否则读环境变量（不明文硬编码）
        self._api_key = api_key or self._read_env_key()
        self._base_url = base_url or os.getenv(_BASE_URL_ENV)

    @staticmethod
    def _read_env_key() -> str | None:
        for name in _API_KEY_ENVS:
            value = os.getenv(name)
            if value:
                return value.strip()
        return None

    def complete(self, messages: list[dict[str, str]]) -> str:
        """最通用：返回原始文本"""
        started = time.monotonic()
        if self._call is not None:
            text = self._call(messages=messages, model=self._model)
            self._log_call(messages, started, text, usage=None)
            return text

        try:
            from openai import OpenAI  # 惰性导入，避免无 key 环境失败
        except ImportError as exc:
            raise LLMUnavailableError("openai SDK 未安装") from exc

        if not self._api_key:
            raise LLMUnavailableError(
                "缺少 LLM API Key，请设置环境变量 OPENAI_API_KEY（或 DEEPSEEK_API_KEY / LLM_API_KEY）"
            )

        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        client = OpenAI(**kwargs)
        response = client.chat.completions.create(model=self._model, messages=messages)  # type: ignore[arg-type]
        text = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        self._log_call(messages, started, text, usage=usage)
        return text

    def _log_call(
        self,
        messages: list[dict[str, str]],
        started: float,
        text: str,
        usage: Any,
    ) -> None:
        """脱敏调用日志：只记 model/base_url/tokens/耗时/成本，不落 prompt 全文与密钥。"""
        elapsed_ms = int((time.monotonic() - started) * 1000)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        if prompt_tokens is None:
            prompt_tokens = _estimate_tokens([m.get("content", "") for m in messages])
        if completion_tokens is None:
            completion_tokens = _estimate_tokens([text])
        cost_usd = round(
            prompt_tokens / 1000 * _PRICING_PER_1K["input"]
            + completion_tokens / 1000 * _PRICING_PER_1K["output"],
            6,
        )
        emit_session_event(
            "llm.call", "llm",
            f"LLM 调用完成 {self._model}（{prompt_tokens}+{completion_tokens} tokens, {elapsed_ms}ms, ${cost_usd:.6f}）",
            model=self._model,
            base_url=self._base_url or "",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            elapsed_ms=elapsed_ms,
            cost_usd=cost_usd,
        )

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """要求模型输出 JSON，解析失败抛 LLMUnavailableError"""
        text = self.complete(messages)
        try:
            result = json.loads(text)
            assert isinstance(result, dict)
            return result
        except (json.JSONDecodeError, AssertionError) as exc:
            raise LLMUnavailableError(f"LLM 返回非 JSON: {exc}") from exc