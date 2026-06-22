"""GSI 事件队列 - 线程安全，支持多消费者"""

import queue
import threading
from typing import List, Optional

from gsi.models import GSIEvent
from utils.log_config import get_logger

logger = get_logger("gsi_event_queue", component="gsi")


class GSIEventQueue:
    """GSI 事件队列"""

    def __init__(self, max_history: int = 100):
        self._queue: queue.Queue = queue.Queue()
        self._history: List[GSIEvent] = []
        self._max_history = max_history
        self._lock = threading.Lock()
        self._subscribers: List[queue.Queue] = []

    def put(self, event: GSIEvent) -> None:
        """入队事件，通知所有订阅者"""
        self._queue.put(event)
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
        for sub in self._subscribers:
            try:
                sub.put_nowait(event)
            except queue.Full:
                pass

    def get(self, timeout: float = 1.0) -> Optional[GSIEvent]:
        """从队列获取事件（阻塞）"""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def subscribe(self, maxsize: int = 50) -> queue.Queue:
        """订阅事件流（SSE 使用）"""
        q = queue.Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        """取消订阅"""
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def get_recent(self, n: int = 20) -> List[GSIEvent]:
        """获取最近 N 条事件"""
        with self._lock:
            return list(self._history[-n:])

    def clear_history(self) -> None:
        """清空历史记录"""
        with self._lock:
            self._history.clear()

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)
