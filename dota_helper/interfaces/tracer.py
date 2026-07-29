"""ITracer 追踪协议 + Span 接口

定义追踪的抽象接口，支持依赖注入替换实现（LangfuseTracer/NoOpTracer/Jaeger）。
"""
from typing import Any, ContextManager, Optional

from typing import Protocol, runtime_checkable


@runtime_checkable
class Span(Protocol):
    """追踪 Span 接口

    表示一个带有时长和属性的追踪区间。
    """

    def set_attribute(self, key: str, value: Any) -> None:
        """设置 Span 属性

        Args:
            key: 属性键
            value: 属性值
        """
        ...

    def set_status(self, status: str) -> None:
        """设置 Span 状态

        Args:
            status: 状态值（"ok" / "error"）
        """
        ...

    def end(self) -> None:
        """结束 Span，计算耗时"""
        ...


@runtime_checkable
class ITracer(Protocol):
    """追踪器接口

    定义 span() 和 event() 方法，支持依赖注入替换实现。
    """

    def span(self, name: str, **kwargs: Any) -> ContextManager[Span]:
        """创建追踪 Span

        支持异步上下文管理器嵌套。

        Args:
            name: Span 名称
            **kwargs: Span 属性

        Returns:
            ContextManager[Span]: Span 上下文管理器
        """
        ...

    def event(self, name: str, **kwargs: Any) -> None:
        """记录追踪事件（即时事件，非 Span）

        Args:
            name: 事件名称
            **kwargs: 事件属性
        """
        ...
