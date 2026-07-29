"""Tracer 核心实现 — Span 创建/管理/嵌套/trace_id 传播

提供内存级追踪实现，支持异步上下文管理器嵌套。
当 Langfuse SDK 可用时，LangfuseTracer 在此基础上桥接到远程追踪。
"""
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional

from dota_helper.observability.logger import get_logger

logger = get_logger("observability.tracer")


class TracerSpan:
    """追踪 Span 实现

    表示一个带有时长和属性的追踪区间。
    支持父子嵌套关系和 trace_id 传播。

    Args:
        name: Span 名称
        trace_id: 追踪 ID（顶层 Span 生成，子 Span 继承）
        parent_id: 父 Span ID
        attributes: 初始属性
    """

    def __init__(
        self,
        name: str,
        trace_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """初始化 Span

        Args:
            name: Span 名称
            trace_id: 追踪 ID
            parent_id: 父 Span ID
            attributes: 初始属性字典
        """
        self.name = name
        self.span_id = f"span_{uuid.uuid4().hex[:12]}"
        self.trace_id = trace_id or f"trace_{uuid.uuid4().hex[:12]}"
        self.parent_id = parent_id
        self._attributes: Dict[str, Any] = attributes or {}
        self._status: str = "ok"
        self._start_time: float = time.monotonic()
        self._end_time: Optional[float] = None

    def set_attribute(self, key: str, value: Any) -> None:
        """设置 Span 属性

        Args:
            key: 属性键
            value: 属性值
        """
        self._attributes[key] = value

    def set_status(self, status: str) -> None:
        """设置 Span 状态

        Args:
            status: 状态值（"ok" / "error"）
        """
        self._status = status

    def end(self) -> None:
        """结束 Span，计算耗时"""
        if self._end_time is None:
            self._end_time = time.monotonic()

    @property
    def duration_ms(self) -> float:
        """Span 耗时（毫秒）

        Returns:
            float: 耗时毫秒数
        """
        end = self._end_time or time.monotonic()
        return (end - self._start_time) * 1000

    @property
    def attributes(self) -> Dict[str, Any]:
        """Span 属性字典

        Returns:
            Dict[str, Any]: 属性字典
        """
        return dict(self._attributes)

    @property
    def status(self) -> str:
        """Span 状态

        Returns:
            str: 状态值
        """
        return self._status

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典

        Returns:
            Dict[str, Any]: Span 字典表示
        """
        return {
            "name": self.name,
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "status": self._status,
            "duration_ms": self.duration_ms,
            "attributes": self._attributes,
        }


class Tracer:
    """Tracer 核心实现

    Span 创建/管理/嵌套/trace_id 传播。
    支持 async with 嵌套，自动维护父子关系。
    """

    def __init__(self) -> None:
        """初始化 Tracer"""
        self._current_span: Optional[TracerSpan] = None
        self._completed_spans: List[TracerSpan] = []

    @asynccontextmanager
    async def span(self, name: str, **kwargs: Any) -> AsyncGenerator[TracerSpan, None]:
        """创建追踪 Span

        支持嵌套，自动维护父子关系和 trace_id 传播。

        Args:
            name: Span 名称
            **kwargs: Span 属性

        Yields:
            TracerSpan: Span 实例
        """
        parent = self._current_span
        trace_id = parent.trace_id if parent else None
        parent_id = parent.span_id if parent else None

        new_span = TracerSpan(
            name=name,
            trace_id=trace_id,
            parent_id=parent_id,
            attributes=kwargs,
        )

        self._current_span = new_span
        logger.debug("Span 开始: name=%s, trace_id=%s", name, new_span.trace_id)

        try:
            yield new_span
        except Exception as e:
            new_span.set_status("error")
            new_span.set_attribute("error", str(e))
            raise
        finally:
            new_span.end()
            self._completed_spans.append(new_span)
            self._current_span = parent
            logger.debug(
                "Span 结束: name=%s, duration_ms=%.1f",
                name,
                new_span.duration_ms,
            )

    def event(self, name: str, **kwargs: Any) -> None:
        """记录追踪事件

        Args:
            name: 事件名称
            **kwargs: 事件属性
        """
        trace_id = self._current_span.trace_id if self._current_span else None
        logger.debug("事件: name=%s, trace_id=%s, attrs=%s", name, trace_id, kwargs)

    @property
    def completed_spans(self) -> List[TracerSpan]:
        """已完成的 Span 列表

        Returns:
            List[TracerSpan]: 已完成的 Span 列表
        """
        return list(self._completed_spans)

    def clear(self) -> None:
        """清除所有已完成的 Span"""
        self._completed_spans.clear()
