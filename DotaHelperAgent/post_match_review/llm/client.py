"""独立 LLM 客户端"""
import os
import asyncio
from typing import List, Dict, Any, Optional

from openai import AsyncOpenAI

from post_match_review.observability.logger import get_logger

logger = get_logger("llm.client")


class LLMClient:
    """独立 LLM 客户端（基于 OpenAI SDK）"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: str = "deepseek-v4-pro",
        max_retries: int = 2,
        timeout: float = 30.0,
    ) -> None:
        """初始化 LLM 客户端

        Args:
            api_key: OpenAI API Key，默认从环境变量 OPENAI_API_KEY 读取
            base_url: OpenAI Base URL，默认从环境变量 OPENAI_BASE_URL 读取
            default_model: 默认模型名称
            max_retries: 网络失败时的最大重试次数
            timeout: 请求超时时间（秒）
        """
        # 支持多种环境变量名（优先级：参数 > OPENAI_API_KEY > DEEPSEEK_API_KEY > LLM_API_KEY）
        self._api_key = (
            api_key
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("LLM_API_KEY")
            or ""
        )
        # 支持多种 base_url 配置
        self._base_url = (
            base_url
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or "https://api.deepseek.com"  # 默认使用 DeepSeek
        )
        self._default_model = default_model
        self._max_retries = max_retries
        self._timeout = timeout

        if not self._api_key:
            logger.warning("OPENAI_API_KEY 未设置，LLM 调用将失败")

        self._client: Optional[AsyncOpenAI] = None
        logger.info(
            "LLM 客户端初始化: model=%s, max_retries=%d, timeout=%.1f",
            self._default_model,
            self._max_retries,
            self._timeout,
        )

    def _get_client(self) -> AsyncOpenAI:
        """获取或创建 AsyncOpenAI 客户端实例

        Returns:
            AsyncOpenAI: 异步 OpenAI 客户端
        """
        if self._client is None:
            client_kwargs: Dict[str, Any] = {
                "api_key": self._api_key,
                "timeout": self._timeout,
            }
            if self._base_url:
                client_kwargs["base_url"] = self._base_url

            self._client = AsyncOpenAI(**client_kwargs)
            logger.debug("创建 AsyncOpenAI 客户端实例")

        return self._client

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> str:
        """调用 LLM 生成回复

        Args:
            messages: OpenAI 风格消息列表
            model: 模型名称，默认使用初始化时指定的模型
            temperature: 温度参数
            **kwargs: 其他传递给 OpenAI API 的参数

        Returns:
            str: 模型回复文本

        Raises:
            Exception: 当所有重试都失败时抛出最后一次异常
        """
        target_model = model or self._default_model
        client = self._get_client()

        last_exception: Optional[Exception] = None

        for attempt in range(self._max_retries + 1):
            try:
                logger.debug(
                    "调用 LLM: model=%s, messages=%d, attempt=%d/%d",
                    target_model,
                    len(messages),
                    attempt + 1,
                    self._max_retries + 1,
                )

                response = await client.chat.completions.create(
                    model=target_model,
                    messages=messages,
                    temperature=temperature,
                    **kwargs,
                )

                content = response.choices[0].message.content or ""
                logger.debug("LLM 响应长度: %d 字符", len(content))

                return content

            except Exception as e:
                last_exception = e
                logger.warning(
                    "LLM 调用失败 (attempt %d/%d): %s",
                    attempt + 1,
                    self._max_retries + 1,
                    str(e),
                )

                if attempt < self._max_retries:
                    wait_time = 2 ** attempt  # 指数退避：1s, 2s
                    logger.info("等待 %.1f 秒后重试...", wait_time)
                    await asyncio.sleep(wait_time)

        logger.error("LLM 调用在 %d 次重试后仍然失败", self._max_retries + 1)
        raise last_exception

    async def close(self) -> None:
        """关闭客户端连接"""
        if self._client is not None:
            await self._client.close()
            self._client = None
            logger.info("LLM 客户端已关闭")
