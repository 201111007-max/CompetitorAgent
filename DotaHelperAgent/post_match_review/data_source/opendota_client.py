"""独立 OpenDota HTTP 客户端"""
import asyncio
from typing import Any, Dict

import httpx

from post_match_review.data_source.exceptions import OpenDotaAPIError
from post_match_review.observability.logger import get_logger

logger = get_logger("data_source.opendota_client")


class OpenDotaClient:
    """独立 OpenDota HTTP 客户端，支持指数退避重试"""

    def __init__(
        self,
        base_url: str = "https://api.opendota.com/api",
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """懒加载 httpx 客户端

        由于 Flask 每个请求可能运行在独立的 event loop 中，
        当检测到 loop 变化时重新创建 client，避免 ``Event loop is closed`` 错误。

        清理旧 client 时捕获所有异常，防止旧 loop 已关闭导致初始化失败。
        """
        loop = asyncio.get_running_loop()
        if (
            self._client is None
            or self._client.is_closed
            or getattr(self, "_loop", None) is not loop
        ):
            if self._client is not None and not self._client.is_closed:
                try:
                    await self._client.aclose()
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "关闭旧 httpx 客户端时忽略异常: %s",
                        str(exc),
                    )
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout),
            )
            self._loop = loop
        return self._client

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def get_match_details(self, match_id: str) -> Dict[str, Any]:
        """获取比赛详情

        Args:
            match_id: 比赛 ID

        Returns:
            Dict[str, Any]: OpenDota 原始响应

        Raises:
            OpenDotaAPIError: API 调用失败
        """
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                client = await self._get_client()
                response = await client.get(f"/matches/{match_id}")
                response.raise_for_status()
                data = response.json()
                logger.info(
                    "获取比赛详情成功: match_id=%s (attempt %d)",
                    match_id,
                    attempt,
                )
                return data
            except httpx.HTTPStatusError as e:
                last_error = e
                status_code = e.response.status_code
                # 4xx 不重试（除 429）
                if 400 <= status_code < 500 and status_code != 429:
                    raise OpenDotaAPIError(
                        f"API 请求失败: HTTP {status_code}",
                        status_code=status_code,
                    ) from e
                logger.warning(
                    "API 请求失败 (attempt %d/%d): HTTP %s",
                    attempt,
                    self._max_retries,
                    status_code,
                )
            except httpx.RequestError as e:
                last_error = e
                logger.warning(
                    "网络请求异常 (attempt %d/%d): %s",
                    attempt,
                    self._max_retries,
                    str(e),
                )

            # 指数退避
            if attempt < self._max_retries:
                backoff = 2 ** (attempt - 1)
                logger.debug("等待 %d 秒后重试...", backoff)
                await asyncio.sleep(backoff)

        raise OpenDotaAPIError(
            f"API 请求失败，已重试 {self._max_retries} 次: {last_error}"
        ) from last_error
