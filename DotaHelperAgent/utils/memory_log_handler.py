"""内存日志处理器

缓存最近 N 条日志，支持实时推送到前端。
"""

import logging
import threading
import queue
import json
from collections import deque
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime


class MemoryLogHandler(logging.Handler):
    """
    内存日志处理器 - 缓存最近 N 条日志，支持实时推送
    """

    def __init__(self, max_entries: int = 1000):
        super().__init__()
        self.max_entries = max_entries
        self._logs: deque = deque(maxlen=max_entries)
        self._session_logs: Dict[str, deque] = {}
        self._lock = threading.RLock()
        self._subscribers: List[Callable] = []
        self._queue = queue.Queue()
        self._running = True

        # 启动后台处理线程
        self._worker = threading.Thread(target=self._process_queue, daemon=True)
        self._worker.start()

    def emit(self, record: logging.LogRecord):
        """接收日志记录"""
        # 同步处理日志，确保立即可用
        self._store_log(record)

    def _process_queue(self):
        """后台处理日志队列"""
        while self._running:
            try:
                record = self._queue.get(timeout=1)
                self._store_log(record)
            except queue.Empty:
                continue

    def _store_log(self, record: logging.LogRecord):
        """存储日志并通知订阅者"""
        log_entry = self._format_record(record)

        with self._lock:
            # 存储到全局队列
            self._logs.append(log_entry)

            # 按 session 分组存储
            session_id = getattr(record, 'session_id', 'global')
            if session_id not in self._session_logs:
                self._session_logs[session_id] = deque(maxlen=self.max_entries)
            self._session_logs[session_id].append(log_entry)

        # 通知订阅者
        for callback in self._subscribers:
            try:
                callback(log_entry)
            except Exception:
                pass

    def _format_record(self, record: logging.LogRecord) -> Dict[str, Any]:
        """格式化日志记录"""
        return {
            "id": f"{record.created}-{record.lineno}",
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self.format(record),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "session_id": getattr(record, 'session_id', 'global'),
            "component": getattr(record, 'component', 'system'),
            "extra_data": getattr(record, 'extra_data', None)
        }

    def get_logs(
        self,
        session_id: Optional[str] = None,
        level: Optional[str] = None,
        component: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        获取日志

        Args:
            session_id: 会话 ID，为 None 则返回所有日志
            level: 日志级别过滤
            component: 组件过滤
            limit: 返回条数限制

        Returns:
            日志条目列表
        """
        with self._lock:
            if session_id and session_id in self._session_logs:
                logs = list(self._session_logs[session_id])
            else:
                logs = list(self._logs)

        # 过滤
        if level:
            logs = [l for l in logs if l['level'] == level.upper()]
        if component:
            logs = [l for l in logs if l['component'] == component]

        # 返回最新的
        return logs[-limit:]

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]):
        """订阅日志更新"""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Dict[str, Any]], None]):
        """取消订阅"""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def get_session_logs(self, session_id: str) -> List[Dict[str, Any]]:
        """获取特定会话的日志"""
        with self._lock:
            if session_id in self._session_logs:
                return list(self._session_logs[session_id])
            return []

    def clear(self, session_id: Optional[str] = None):
        """清空日志"""
        with self._lock:
            if session_id:
                # 清空特定会话的日志
                if session_id in self._session_logs:
                    self._session_logs[session_id].clear()
                # 从全局日志中移除该会话的日志
                filtered_logs = [log for log in self._logs if log.get('session_id') != session_id]
                self._logs.clear()
                self._logs.extend(filtered_logs)
            else:
                # 清空所有日志
                self._logs.clear()
                self._session_logs.clear()

    def close(self):
        """关闭处理器"""
        self._running = False
        self._worker.join(timeout=2)
        super().close()


# 全局内存日志处理器实例
_memory_handler: Optional[MemoryLogHandler] = None


def get_memory_handler(max_entries: int = 1000) -> MemoryLogHandler:
    """获取内存日志处理器单例"""
    global _memory_handler
    if _memory_handler is None:
        _memory_handler = MemoryLogHandler(max_entries)
    return _memory_handler


def reset_memory_handler():
    """重置内存日志处理器单例（用于测试）"""
    global _memory_handler
    if _memory_handler is not None:
        _memory_handler.close()
        _memory_handler = None
