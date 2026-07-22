"""SSE 进度事件发射器"""
import asyncio
from typing import AsyncGenerator, Optional

from post_match_review.domain_types.events import ProgressEvent
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.report.progress")


class ProgressEmitter:
    """SSE 进度事件发射器

    通过内部异步队列连接复盘编排器与 SSE 流消费者，支持在复盘执行
    过程中实时推送进度事件。
    """

    def __init__(self) -> None:
        """初始化发射器"""
        self._queue: asyncio.Queue[Optional[ProgressEvent]] = asyncio.Queue()
        self._closed = False

    async def emit(self, event: ProgressEvent) -> None:
        """发送单个事件

        Args:
            event: 进度事件
        """
        if self._closed:
            logger.warning("尝试向已关闭的发射器发送事件: %s", event.event)
            return
        await self._queue.put(event)

    async def stream(self) -> AsyncGenerator[ProgressEvent, None]:
        """生成事件流

        Yields:
            ProgressEvent: 进度事件
        """
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event

    def close(self) -> None:
        """关闭事件流"""
        self._closed = True
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            logger.warning("发射器队列已满，无法放入结束标记")
