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
    内存日志处理器 - 缓存最近 N 条日志，支持实时推送和持久化
    """

    def __init__(self, max_entries: int = 1000, enable_persistence: bool = False):
        super().__init__()
        self.max_entries = max_entries
        self.enable_persistence = enable_persistence
        self._logs: deque = deque(maxlen=max_entries)
        self._session_logs: Dict[str, deque] = {}
        
        self._trace_index: Dict[str, List[int]] = {}
        self._error_index: List[int] = []
        self._log_counter = 0
        
        self._lock = threading.RLock()
        self._subscribers: List[Callable] = []
        self._queue = queue.Queue()
        self._running = True
        
        self._persistence = None
        if enable_persistence:
            try:
                from utils.trace_persistence import get_trace_persistence
                self._persistence = get_trace_persistence()
            except Exception as e:
                print(f"初始化 Trace 持久化失败: {e}")
                self.enable_persistence = False

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

    def _extract_trace_id(self, log_entry: Dict[str, Any]) -> Optional[str]:
        """从日志条目中提取 trace_id"""
        if log_entry.get('trace_id'):
            return log_entry['trace_id']
        
        trace = log_entry.get('trace')
        if trace and isinstance(trace, dict) and trace.get('trace_id'):
            return trace['trace_id']
        
        extra = log_entry.get('extra_data') or {}
        if isinstance(extra, dict) and extra.get('trace_id'):
            return extra['trace_id']
        
        return None

    def _store_log(self, record: logging.LogRecord):
        """存储日志并建立索引"""
        log_entry = self._format_record(record)

        with self._lock:
            idx = self._log_counter
            
            self._logs.append(log_entry)
            self._log_counter += 1
            
            trace_id = self._extract_trace_id(log_entry)
            if trace_id:
                if trace_id not in self._trace_index:
                    self._trace_index[trace_id] = []
                self._trace_index[trace_id].append(idx)
                
                if self.enable_persistence and self._persistence:
                    try:
                        self._persistence.save_trace_log(trace_id, log_entry)
                    except Exception as e:
                        print(f"持久化 Trace 日志失败: {e}")
            
            if log_entry.get('level') == 'ERROR':
                self._error_index.append(idx)
            
            session_id = getattr(record, 'session_id', 'global')
            if session_id not in self._session_logs:
                self._session_logs[session_id] = deque(maxlen=self.max_entries)
            self._session_logs[session_id].append(log_entry)

        for callback in self._subscribers:
            try:
                callback(log_entry)
            except Exception:
                pass

    def _format_record(self, record: logging.LogRecord) -> Dict[str, Any]:
        """格式化日志记录
        
        确保返回的日志格式统一：
        - message 字段是纯文本
        - trace 字段是字典或 None
        - extra_data 字段是字典或 None
        """
        trace = getattr(record, 'trace', None)
        trace_id = getattr(record, 'trace_id', None)
        
        if trace and hasattr(trace, 'to_dict'):
            trace = trace.to_dict()
        
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        
        extra_data = getattr(record, 'extra_data', None)
        if extra_data is not None and not isinstance(extra_data, dict):
            extra_data = {'value': str(extra_data)}
        
        return {
            "id": f"{record.created}-{record.lineno}",
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "session_id": getattr(record, 'session_id', 'global'),
            "component": getattr(record, 'component', 'system'),
            "extra_data": extra_data,
            "trace": trace,
            "trace_id": trace_id
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

        if level:
            logs = [l for l in logs if l['level'] == level.upper()]
        if component:
            logs = [l for l in logs if l['component'] == component]

        return logs[-limit:]

    def get_trace_logs(self, trace_id: str) -> List[Dict[str, Any]]:
        """直接通过索引获取日志
        
        Args:
            trace_id: Trace ID
            
        Returns:
            该 trace_id 对应的所有日志
        """
        with self._lock:
            indices = self._trace_index.get(trace_id, [])
            logs = []
            all_logs = list(self._logs)
            for idx in indices:
                if idx < len(all_logs):
                    logs.append(all_logs[idx])
            return logs
    
    def get_errors(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近的错误日志
        
        Args:
            limit: 返回条数限制
            
        Returns:
            最近的错误日志列表
        """
        with self._lock:
            all_logs = list(self._logs)
            errors = []
            for idx in self._error_index[-limit:]:
                if idx < len(all_logs):
                    errors.append(all_logs[idx])
            return errors
    
    def persist_trace(self, trace_data: Dict[str, Any]) -> bool:
        """持久化 Trace 信息
        
        Args:
            trace_data: Trace 数据字典
        
        Returns:
            是否保存成功
        """
        if not self.enable_persistence or not self._persistence:
            return False
        
        try:
            return self._persistence.save_trace(trace_data)
        except Exception as e:
            print(f"持久化 Trace 失败: {e}")
            return False
    
    def get_persisted_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """从数据库获取 Trace 信息
        
        Args:
            trace_id: Trace ID
        
        Returns:
            Trace 数据字典
        """
        if not self.enable_persistence or not self._persistence:
            return None
        
        try:
            return self._persistence.get_trace(trace_id)
        except Exception as e:
            print(f"获取持久化 Trace 失败: {e}")
            return None
    
    def get_persisted_trace_logs(self, trace_id: str) -> List[Dict[str, Any]]:
        """从数据库获取 Trace 相关日志
        
        Args:
            trace_id: Trace ID
        
        Returns:
            日志列表
        """
        if not self.enable_persistence or not self._persistence:
            return []
        
        try:
            return self._persistence.get_trace_logs(trace_id)
        except Exception as e:
            print(f"获取持久化 Trace 日志失败: {e}")
            return []

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
        """清空日志和索引"""
        with self._lock:
            if session_id:
                if session_id in self._session_logs:
                    self._session_logs[session_id].clear()
                
                self._trace_index.clear()
                self._error_index.clear()
                
                filtered_logs = [log for log in self._logs if log.get('session_id') != session_id]
                self._logs.clear()
                self._logs.extend(filtered_logs)
            else:
                self._logs.clear()
                self._session_logs.clear()
                self._trace_index.clear()
                self._error_index.clear()
                self._log_counter = 0

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
