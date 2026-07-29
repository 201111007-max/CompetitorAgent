"""NoOpTracer — ITracer 的空实现

SDK 缺失时的默认降级实现，所有方法为 no-op，零开销。
"""
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from dota_helper.interfaces.tracer import ITracer, Span
from dota_helper.observability.logger import get_logger

logger = get_logger("observability.noop_tracer")


class NoOpSpan:
    """空 Span 实现

    所有方法为 no-op，不记录任何数据。
    """

    def set_attribute(self, key: str, value: Any) -> None:
        """no-op"""
        pass

    def set_status(self, status: str) -> None:
        """no-op"""
        pass

    def end(self) -> None:
        """no-op"""
        pass


class NoOpTracer:
    """NoOp 追踪器 — ITracer 的空实现

    SDK 缺失时的默认降级实现，所有方法为 no-op，零开销。
    项目在无 Langfuse SDK 时正常运行。
    """

    @asynccontextmanager
    async def span(self, name: str, **kwargs: Any) -> AsyncGenerator[NoOpSpan, None]:
        """创建空 Span（no-op）

        Args:
            name: Span 名称（忽略）
            **kwargs: Span 属性（忽略）

        Yields:
            NoOpSpan: 空.Span 实例
        """
        yield NoOpSpan()

    def event(self, name: str, **kwargs: Any) -> None:
        """记录空事件（no-op）

        Args:
            name: 事件名称（忽略）
            **kwargs: 事件属性（忽略）
        """
        pass
