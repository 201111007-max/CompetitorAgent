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
    
    使用相对索引（deque 中的位置）而非全局计数器，避免计数器无限增长。
    """

    def __init__(self, max_entries: int = 1000, enable_persistence: bool = False):
        super().__init__()
        self.max_entries = max_entries
        self.enable_persistence = enable_persistence
        self._logs: deque = deque(maxlen=max_entries)
        self._session_logs: Dict[str, deque] = {}
        
        # 使用相对索引，不需要全局计数器
        self._trace_index: Dict[str, List[int]] = {}
        self._error_index: List[int] = []
        
        self._lock = threading.RLock()
        self._subscribers: List[Callable] = []
        self._queue = queue.Queue()
        self._running = True
        
        self._persistence = None
        self._persistence_queue = None
        self._persistence_worker = None
        
        if enable_persistence:
            try:
                from utils.trace_persistence import get_trace_persistence
                self._persistence = get_trace_persistence()
                
                # 创建持久化队列和后台线程
                self._persistence_queue = queue.Queue()
                self._persistence_worker = threading.Thread(
                    target=self._process_persistence_queue, daemon=True
                )
                self._persistence_worker.start()
            except Exception as e:
                self._get_logger().error(f"初始化 Trace 持久化失败: {e}")
                self.enable_persistence = False

        self._worker = threading.Thread(target=self._process_queue, daemon=True)
        self._worker.start()
    
    def _get_logger(self):
        """获取 logger 实例"""
        return logging.getLogger(__name__)

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
    
    def _process_persistence_queue(self):
        """后台处理持久化队列
        
        异步处理持久化任务，避免阻塞日志处理。
        """
        while self._running:
            try:
                trace_id, log_entry = self._persistence_queue.get(timeout=1)
                if self._persistence:
                    try:
                        self._persistence.save_trace_log(trace_id, log_entry)
                    except Exception as e:
                        self._get_logger().error(f"持久化 Trace 日志失败: {e}")
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

    def _cleanup_invalid_indices(self):
        """清理失效的索引
        
        当 deque 滚动时，所有旧索引都会失效。
        由于使用相对索引（deque 中的位置），当添加新日志导致旧日志被删除时，
        需要将所有索引减 1（相当于所有日志向前移动了一位）。
        
        优化策略：当 deque 滚动时，清空所有索引并重建。
        """
        # 清空所有索引
        self._trace_index.clear()
        self._error_index.clear()
        
        # 重建索引
        for i, log in enumerate(self._logs):
            trace_id = self._extract_trace_id(log)
            if trace_id:
                if trace_id not in self._trace_index:
                    self._trace_index[trace_id] = []
                self._trace_index[trace_id].append(i)
            
            if log.get('level') == 'ERROR':
                self._error_index.append(i)

    def _store_log(self, record: logging.LogRecord):
        """存储日志并建立索引
        
        使用相对索引（deque 中的位置），避免全局计数器无限增长。
        """
        log_entry = self._format_record(record)

        with self._lock:
            old_len = len(self._logs)
            
            # 使用当前 deque 长度作为新日志的索引
            idx = len(self._logs)
            
            self._logs.append(log_entry)
            new_len = len(self._logs)
            
            # 如果 deque 滚动（满了），需要重建索引
            if new_len < old_len + 1:
                self._cleanup_invalid_indices()
            else:
                # 正常添加，建立索引
                trace_id = self._extract_trace_id(log_entry)
                if trace_id:
                    if trace_id not in self._trace_index:
                        self._trace_index[trace_id] = []
                    self._trace_index[trace_id].append(idx)
                    
                    # 异步持久化（如果启用）
                    if self.enable_persistence and self._persistence_queue:
                        self._persistence_queue.put((trace_id, log_entry))
                
                if log_entry.get('level') == 'ERROR':
                    self._error_index.append(idx)
            
            session_id = getattr(record, 'session_id', 'global')
            if session_id not in self._session_logs:
                self._session_logs[session_id] = deque(maxlen=self.max_entries)
            self._session_logs[session_id].append(log_entry)

        # 锁外调用回调，避免阻塞
        subscribers = list(self._subscribers)
        for callback in subscribers:
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
            if not indices:
                return []
            
            logs = []
            # 直接使用索引访问 deque（索引就是 deque 中的位置）
            for idx in indices:
                try:
                    logs.append(self._logs[idx])
                except IndexError:
                    # 索引失效，跳过
                    pass
            
            return logs
    
    def get_errors(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近的错误日志
        
        Args:
            limit: 返回条数限制
            
        Returns:
            最近的错误日志列表
        """
        with self._lock:
            if not self._error_index:
                return []
            
            errors = []
            # 只取最近的 limit 条错误索引
            recent_error_indices = self._error_index[-limit:]
            
            # 直接使用索引访问 deque（索引就是 deque 中的位置）
            for idx in recent_error_indices:
                try:
                    errors.append(self._logs[idx])
                except IndexError:
                    # 索引失效，跳过
                    pass
            
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
            self._get_logger().error(f"持久化 Trace 失败: {e}")
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
            self._get_logger().error(f"获取持久化 Trace 失败: {e}")
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
            self._get_logger().error(f"获取持久化 Trace 日志失败: {e}")
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
        """清空日志和索引
        
        Args:
            session_id: 会话 ID，如果指定则只清空该会话的日志和索引
        """
        with self._lock:
            if session_id:
                # 只清空指定 session 的日志和索引
                
                # 1. 删除该 session 的会话日志
                if session_id in self._session_logs:
                    del self._session_logs[session_id]
                
                # 2. 找出该 session 相关的所有 trace_id
                session_trace_ids = set()
                
                for i in range(len(self._logs)):
                    log = self._logs[i]
                    if log.get('session_id') == session_id:
                        trace_id = self._extract_trace_id(log)
                        if trace_id:
                            session_trace_ids.add(trace_id)
                
                # 3. 只删除该 session 相关的 trace 索引
                for trace_id in session_trace_ids:
                    if trace_id in self._trace_index:
                        del self._trace_index[trace_id]
                
                # 4. 重建错误索引（排除该 session）
                new_error_index = []
                for idx in self._error_index:
                    try:
                        log = self._logs[idx]
                        if log.get('session_id') != session_id:
                            new_error_index.append(idx)
                    except IndexError:
                        pass
                self._error_index = new_error_index
                
                # 5. 删除该 session 的日志（从主 deque）
                filtered_logs = [log for log in self._logs if log.get('session_id') != session_id]
                self._logs.clear()
                self._logs.extend(filtered_logs)
                
                # 6. 重建所有索引（因为 deque 中的位置已改变）
                self._cleanup_invalid_indices()
                
            else:
                # 清空所有日志和索引
                self._logs.clear()
                self._session_logs.clear()
                self._trace_index.clear()
                self._error_index.clear()

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
