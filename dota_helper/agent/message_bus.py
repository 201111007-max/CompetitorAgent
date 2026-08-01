"""Agent 间消息总线 — 发布/订阅模式

支持子代理之间交换中间结果和状态信息。
事件类型：RESULT_READY, ERROR, STATUS_CHANGE, CUSTOM
"""
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Awaitable

from dota_helper.observability.logger import get_logger

logger = get_logger("agent.message_bus")


class EventType(Enum):
    """消息总线事件类型"""
    RESULT_READY = "result_ready"       # 子代理结果就绪
    ERROR = "error"                     # 子代理执行错误
    STATUS_CHANGE = "status_change"     # 子代理状态变更
    CUSTOM = "custom"                   # 自定义事件


@dataclass
class Message:
    """消息总线中的一条消息"""
    event_type: EventType
    sender: str                         # 发送者标识（如子代理名称）
    payload: Any                        # 消息内容
    timestamp: float = field(default_factory=time.time)
    message_id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:8]}")


# 消息处理回调类型
MessageHandler = Callable[[Message], Awaitable[None]]


class MessageBus:
    """消息总线

    基于发布/订阅模式，支持：
    - 按事件类型订阅
    - 按发送者过滤
    - 异步消息分发
    - 消息历史查询
    """

    def __init__(self, max_history: int = 1000) -> None:
        """初始化消息总线

        Args:
            max_history: 最大历史消息数（默认 1000）
        """
        self._subscribers: Dict[EventType, List[tuple[MessageHandler, Optional[str]]]] = {}
        self._history: List[Message] = []
        self._max_history = max_history
        self._lock = asyncio.Lock()
        logger.info("消息总线初始化: max_history=%d", max_history)

    def subscribe(
        self,
        event_type: EventType,
        handler: MessageHandler,
        sender_filter: Optional[str] = None,
    ) -> None:
        """订阅指定类型的事件

        Args:
            event_type: 事件类型
            handler: 异步处理函数
            sender_filter: 可选，只接收指定发送者的消息
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append((handler, sender_filter))
        logger.debug(
            "订阅事件: type=%s, sender_filter=%s",
            event_type.value, sender_filter or "any",
        )

    def unsubscribe(self, event_type: EventType, handler: MessageHandler) -> bool:
        """取消订阅

        Args:
            event_type: 事件类型
            handler: 之前注册的处理函数

        Returns:
            bool: 是否成功取消
        """
        if event_type not in self._subscribers:
            return False
        before = len(self._subscribers[event_type])
        self._subscribers[event_type] = [
            (h, f) for h, f in self._subscribers[event_type] if h != handler
        ]
        removed = before - len(self._subscribers[event_type])
        if removed > 0:
            logger.debug("取消订阅: type=%s", event_type.value)
        return removed > 0

    async def publish(self, message: Message) -> int:
        """发布消息

        将消息分发给所有匹配的订阅者，并记录到历史。

        Args:
            message: 消息对象

        Returns:
            int: 接收该消息的订阅者数量
        """
        # 记录历史
        async with self._lock:
            self._history.append(message)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        # 分发
        handlers = self._subscribers.get(message.event_type, [])
        if not handlers:
            logger.debug("消息无订阅者: type=%s, sender=%s", message.event_type.value, message.sender)
            return 0

        delivered = 0
        for handler, sender_filter in handlers:
            if sender_filter is not None and message.sender != sender_filter:
                continue
            try:
                await handler(message)
                delivered += 1
            except Exception as e:
                logger.warning(
                    "消息处理失败: type=%s, sender=%s, error=%s",
                    message.event_type.value, message.sender, str(e),
                )

        logger.debug(
            "消息已分发: type=%s, sender=%s, delivered=%d/%d",
            message.event_type.value, message.sender, delivered, len(handlers),
        )
        return delivered

    async def publish_result_ready(self, sender: str, result: Any) -> int:
        """快捷发布 RESULT_READY 事件

        Args:
            sender: 发送者标识
            result: 结果数据

        Returns:
            int: 接收该消息的订阅者数量
        """
        return await self.publish(Message(
            event_type=EventType.RESULT_READY,
            sender=sender,
            payload=result,
        ))

    async def publish_error(self, sender: str, error: Exception) -> int:
        """快捷发布 ERROR 事件

        Args:
            sender: 发送者标识
            error: 异常对象

        Returns:
            int: 接收该消息的订阅者数量
        """
        return await self.publish(Message(
            event_type=EventType.ERROR,
            sender=sender,
            payload={"error_type": type(error).__name__, "error_msg": str(error)},
        ))

    async def publish_status(self, sender: str, status: str) -> int:
        """快捷发布 STATUS_CHANGE 事件

        Args:
            sender: 发送者标识
            status: 状态描述

        Returns:
            int: 接收该消息的订阅者数量
        """
        return await self.publish(Message(
            event_type=EventType.STATUS_CHANGE,
            sender=sender,
            payload={"status": status},
        ))

    def get_history(
        self,
        event_type: Optional[EventType] = None,
        sender: Optional[str] = None,
        limit: int = 50,
    ) -> List[Message]:
        """查询消息历史

        Args:
            event_type: 可选，按事件类型过滤
            sender: 可选，按发送者过滤
            limit: 最大返回条数

        Returns:
            List[Message]: 符合条件的消息列表（按时间倒序）
        """
        result = self._history
        if event_type is not None:
            result = [m for m in result if m.event_type == event_type]
        if sender is not None:
            result = [m for m in result if m.sender == sender]
        return result[-limit:]

    def clear_history(self) -> None:
        """清空消息历史"""
        self._history.clear()
        logger.debug("消息历史已清空")

    @property
    def history_count(self) -> int:
        """历史消息数量"""
        return len(self._history)

    @property
    def subscriber_count(self) -> int:
        """订阅者总数"""
        return sum(len(handlers) for handlers in self._subscribers.values())
