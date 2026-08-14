"""LLM Client 抽象：驱动维度分析，LLM 不可用时降级

M1 提供：
- LLMClient：基于 openai SDK 的调用封装（parse/summarize 语义化方法）
- 可注入 mock，供测试与规则降级

可靠性（设计文档 36）：
- 可重试错误（429/408/5xx/连接/超时）指数退避重试（≤max_retries）
- 多模型 fallback 链：主模型重试耗尽自动切换 fallback_models
- 每次调用可配置超时（连接 + 读）
- 不可重试错误（401/400/404）直接抛、不浪费重试；全灭抛 LLMUnavailableError 降级规则

凭据与端点通过环境变量控制（不明文落码）：
- OPENAI_API_KEY：API Key（兼容 DEEPSEEK_API_KEY / LLM_API_KEY 别名）
- OPENAI_BASE_URL：OpenAI 兼容端点（DeepSeek 等），默认官方 OpenAI
"""
from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from typing import Any, Callable

from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.observability.logger import emit_session_event

logger = logging.getLogger("competitor_agent.llm.client")

# 脱敏 LLM 调用日志的粗略计价（美元/千 token），仅用于可观测性展示
_PRICING_PER_1K = {"input": 0.0003, "output": 0.0006}  # DeepSeek 量级近似

# 可重试 HTTP 状态码：429 限流 / 408 请求超时 / 5xx 服务端错误
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
# 异常类名启发式（openai SDK 的 RateLimitError / APIConnectionError / APITimeoutError /
# InternalServerError 与内置 TimeoutError / ConnectionError 等）
_RETRYABLE_ERR_FRAGMENTS = (
    "ratelimit",
    "apiconnection",
    "apitimeout",
    "internalserver",
    "timeout",
    "connection",
)


def _estimate_tokens(texts: list[str]) -> int:
    return sum(len(t) // 4 for t in texts)


# 兼容别名链：OPENAI_API_KEY > DEEPSEEK_API_KEY > LLM_API_KEY
_API_KEY_ENVS = ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "LLM_API_KEY")
_BASE_URL_ENV = "OPENAI_BASE_URL"


class LLMClient:
    """统一 LLM 调用封装（可注入 callable 便于测试）

    可靠性（设计文档 36）：可重试错误指数退避重试 → 多模型 fallback 链 →
    全灭抛 LLMUnavailableError 降级规则；不可重试错误（401/400/404）直接抛。
    """

    def __init__(
        self,
        call_func: Callable[..., str] | None = None,
        model: str = "deepseek-chat",
        api_key: str | None = None,
        base_url: str | None = None,
        fallback_models: list[str] | None = None,
        timeout: float | None = None,
        max_retries: int = 3,
        backoff: float = 1.0,
    ) -> None:
        # call_func: (messages, **kwargs) -> str；默认走 openai SDK（惰性导入）
        self._call = call_func
        self._model = model
        self._fallback_models = list(fallback_models) if fallback_models else []
        self._timeout = timeout
        self._max_retries = max(1, int(max_retries))
        self._backoff = max(0.0, float(backoff))
        # 显式传入优先，否则读环境变量（不明文硬编码）
        self._api_key = api_key or self._read_env_key()
        self._base_url = base_url or os.getenv(_BASE_URL_ENV)
        # 累计调用成本（设计文档 37：真实评测报告成本核算，复用 _log_call 的 cost_usd）
        self.total_cost_usd = 0.0
        # 成本累计锁：并行编排（设计文档 33）多线程并发调用时原子累加
        self._cost_lock = threading.Lock()

    @staticmethod
    def has_api_key() -> bool:
        """是否有可用的 API Key（真实评测前置校验，设计文档 37）。"""
        return LLMClient._read_env_key() is not None

    @staticmethod
    def _read_env_key() -> str | None:
        for name in _API_KEY_ENVS:
            value = os.getenv(name)
            if value:
                return value.strip()
        return None

    def complete(self, messages: list[dict[str, str]]) -> str:
        """最通用：返回原始文本（带重试 + 多模型 fallback + 超时）"""
        started = time.monotonic()
        if self._call is not None:
            return self._attempt_models(
                messages,
                started,
                lambda model: self._call(messages=messages, model=model),
            )

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

        def attempt(model: str) -> Any:
            create_kwargs: dict[str, Any] = {"model": model, "messages": messages}
            if self._timeout is not None:
                create_kwargs["timeout"] = self._timeout
            return client.chat.completions.create(**create_kwargs)  # type: ignore[arg-type]

        return self._attempt_models(messages, started, attempt)

    def _attempt_models(
        self,
        messages: list[dict[str, str]],
        started: float,
        attempt_fn: Callable[[str], Any],
    ) -> str:
        """逐模型 × 逐次重试：可重试错误退避重试 → 下一个 fallback 模型 → 全灭抛错。"""
        models = [self._model, *self._fallback_models]
        last_exc: Exception | None = None
        saw_timeout = False
        total_attempts = 0
        for model in models:
            for attempt in range(1, self._max_retries + 1):
                total_attempts += 1
                try:
                    raw = attempt_fn(model)
                    text, usage = self._extract_text_and_usage(raw)
                    self._log_call(
                        messages,
                        started,
                        text,
                        usage=usage,
                        attempts=total_attempts,
                        final_model=model,
                        retried=total_attempts > 1,
                        timed_out=saw_timeout,
                    )
                    return text
                except Exception as exc:  # noqa: BLE001 —— 聚合各类 SDK/mock 错误统一判定
                    last_exc = exc
                    if self._is_timeout(exc):
                        saw_timeout = True
                    if not self._should_retry(exc):
                        raise
                    if attempt < self._max_retries:
                        self._sleep_backoff(attempt)
        raise LLMUnavailableError(
            f"LLM 调用失败：{len(models)} 个模型 × {self._max_retries} 次重试全部耗尽"
        ) from last_exc

    @staticmethod
    def _extract_text_and_usage(raw: Any) -> tuple[str, Any]:
        """从注入 call_func 的 str 或 openai SDK 响应对象中抽取文本与用量。"""
        if isinstance(raw, str):
            return raw, None
        if isinstance(raw, dict):
            choices = raw.get("choices") or []
            content = (choices[0].get("message", {}).get("content") if choices else None) or ""
            return content, raw.get("usage")
        if getattr(raw, "choices", None) is not None:
            content = getattr(raw.choices[0], "message", None)
            content = getattr(content, "content", None) or ""
            return content, getattr(raw, "usage", None)
        raise LLMUnavailableError(f"LLM 返回无法解析的类型: {type(raw).__name__}")

    @staticmethod
    def _should_retry(exc: Exception) -> bool:
        """可重试判定：429/408/5xx 状态码，或异常类名启发式（限流/连接/超时/服务端）。"""
        status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            return status in _RETRYABLE_STATUS or 500 <= status < 600
        name = type(exc).__name__.lower()
        return any(frag in name for frag in _RETRYABLE_ERR_FRAGMENTS)

    @staticmethod
    def _is_timeout(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        if status == 408:
            return True
        return "timeout" in type(exc).__name__.lower()

    def _sleep_backoff(self, attempt: int) -> None:
        """指数退避 + 抖动（attempt 从 1 起：1s, 2s, 4s…）。"""
        delay = self._backoff * (2 ** (attempt - 1))
        time.sleep(delay + random.uniform(0, delay * 0.25))

    def _log_call(
        self,
        messages: list[dict[str, str]],
        started: float,
        text: str,
        usage: Any,
        attempts: int = 1,
        final_model: str | None = None,
        retried: bool = False,
        timed_out: bool = False,
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
        with self._cost_lock:
            self.total_cost_usd = round(self.total_cost_usd + cost_usd, 6)
        emit_session_event(
            "llm.call", "llm",
            f"LLM 调用完成 {final_model or self._model}（{prompt_tokens}+{completion_tokens} tokens, "
            f"{elapsed_ms}ms, ${cost_usd:.6f}）",
            model=final_model or self._model,
            base_url=self._base_url or "",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            elapsed_ms=elapsed_ms,
            cost_usd=cost_usd,
            attempts=attempts,
            retried=retried,
            timed_out=timed_out,
        )

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """要求模型输出 JSON，解析失败抛 LLMUnavailableError（底层走带重试的 complete）"""
        text = self.complete(messages)
        try:
            result = json.loads(text)
            assert isinstance(result, dict)
            return result
        except (json.JSONDecodeError, AssertionError) as exc:
            raise LLMUnavailableError(f"LLM 返回非 JSON: {exc}") from exc
