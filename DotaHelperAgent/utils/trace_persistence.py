"""Trace 持久化模块

将 Trace 信息持久化到 SQLite 数据库，支持历史查询和长期存储。

功能：
- 保存 Trace 信息到数据库
- 查询历史 Trace
- 查询会话相关的 Trace
- 统计 Trace 信息
"""

import sqlite3
import json
import threading
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class ConnectionManager:
    """SQLite 连接管理器
    
    使用线程本地存储管理连接，避免多线程共享连接的问题。
    SQLite 连接不能跨线程使用，所以每个线程维护自己的连接。
    """
    
    def __init__(self, db_path: str, max_idle_time: float = 300):
        """初始化连接管理器
        
        Args:
            db_path: 数据库文件路径
            max_idle_time: 连接最大空闲时间（秒），默认300秒
        """
        self.db_path = db_path
        self.max_idle_time = max_idle_time
        self._local = threading.local()
        self._lock = threading.Lock()
    
    def get_connection(self) -> sqlite3.Connection:
        """获取当前线程的连接
        
        如果当前线程没有连接，则创建新连接。
        """
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            self._local.connection = conn
            self._local.last_used = time.time()
        
        self._local.last_used = time.time()
        return self._local.connection
    
    def close_connection(self):
        """关闭当前线程的连接"""
        if hasattr(self._local, 'connection') and self._local.connection:
            try:
                self._local.connection.close()
            except Exception:
                pass
            self._local.connection = None
    
    def cleanup_idle_connections(self):
        """清理空闲超时的连接
        
        注意：由于使用线程本地存储，无法直接清理其他线程的连接。
        实际清理会在各线程下次访问时进行。
        """
        pass


class TracePersistence:
    """Trace 持久化管理器"""
    
    def __init__(self, db_path: Optional[str] = None):
        """初始化持久化管理器
        
        Args:
            db_path: 数据库文件路径，默认为 logs/traces.db
        """
        if db_path is None:
            log_dir = Path(__file__).parent.parent / "logs"
            log_dir.mkdir(exist_ok=True)
            db_path = str(log_dir / "traces.db")
        
        self.db_path = db_path
        self._lock = threading.RLock()
        self._connection_manager = ConnectionManager(db_path)
        self._init_database()
    
    @contextmanager
    def _get_connection(self):
        """获取数据库连接
        
        使用连接管理器获取线程本地连接。
        """
        conn = self._connection_manager.get_connection()
        try:
            yield conn
        except Exception:
            # 发生异常时关闭连接
            self._connection_manager.close_connection()
            raise
    
    def _init_database(self):
        """初始化数据库表结构"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS traces (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trace_id TEXT NOT NULL,
                        span_id TEXT NOT NULL,
                        parent_span_id TEXT,
                        session_id TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        start_time REAL NOT NULL,
                        duration_ms REAL,
                        status TEXT DEFAULT 'running',
                        metadata TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_trace_id ON traces(trace_id)
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_session_id ON traces(session_id)
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_start_time ON traces(start_time)
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_status ON traces(status)
                """)
                
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trace_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trace_id TEXT NOT NULL,
                        span_id TEXT,
                        log_level TEXT NOT NULL,
                        log_message TEXT NOT NULL,
                        log_data TEXT,
                        timestamp REAL NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (trace_id) REFERENCES traces(trace_id)
                    )
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_trace_log_trace_id ON trace_logs(trace_id)
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_trace_log_timestamp ON trace_logs(timestamp)
                """)
                
                conn.commit()
    
    def save_trace(self, trace_data: Dict[str, Any]) -> bool:
        """保存 Trace 信息
        
        Args:
            trace_data: Trace 数据字典，包含 trace_id, span_id, session_id, operation 等
        
        Returns:
            是否保存成功
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        INSERT OR REPLACE INTO traces 
                        (trace_id, span_id, parent_span_id, session_id, operation, 
                         start_time, duration_ms, status, metadata, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        trace_data.get('trace_id'),
                        trace_data.get('span_id'),
                        trace_data.get('parent_span_id'),
                        trace_data.get('session_id'),
                        trace_data.get('operation'),
                        trace_data.get('start_time'),
                        trace_data.get('duration_ms'),
                        trace_data.get('status', 'running'),
                        json.dumps(trace_data.get('metadata', {}), ensure_ascii=False),
                        datetime.now().isoformat()
                    ))
                    
                    conn.commit()
                    return True
            except Exception as e:
                logger.error(f"保存 Trace 失败: {e}")
                return False
    
    def save_trace_log(self, trace_id: str, log_data: Dict[str, Any]) -> bool:
        """保存 Trace 相关的日志
        
        Args:
            trace_id: Trace ID
            log_data: 日志数据
        
        Returns:
            是否保存成功
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        INSERT INTO trace_logs 
                        (trace_id, span_id, log_level, log_message, log_data, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        trace_id,
                        log_data.get('span_id'),
                        log_data.get('level'),
                        log_data.get('message'),
                        json.dumps(log_data, ensure_ascii=False),
                        log_data.get('timestamp')
                    ))
                    
                    conn.commit()
                    return True
            except Exception as e:
                logger.error(f"保存 Trace 日志失败: {e}")
                return False
    
    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """获取 Trace 信息
        
        Args:
            trace_id: Trace ID
        
        Returns:
            Trace 数据字典
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        SELECT * FROM traces WHERE trace_id = ?
                    """, (trace_id,))
                    
                    row = cursor.fetchone()
                    if row:
                        return self._row_to_dict(row)
                    return None
            except Exception as e:
                logger.error(f"获取 Trace 失败: {e}")
                return None
    
    def get_trace_logs(self, trace_id: str) -> List[Dict[str, Any]]:
        """获取 Trace 相关的日志
        
        Args:
            trace_id: Trace ID
        
        Returns:
            日志列表
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        SELECT * FROM trace_logs 
                        WHERE trace_id = ? 
                        ORDER BY timestamp ASC
                    """, (trace_id,))
                    
                    rows = cursor.fetchall()
                    return [self._log_row_to_dict(row) for row in rows]
            except Exception as e:
                logger.error(f"获取 Trace 日志失败: {e}")
                return []
    
    def get_session_traces(self, session_id: str) -> List[Dict[str, Any]]:
        """获取会话相关的所有 Trace
        
        Args:
            session_id: 会话 ID
        
        Returns:
            Trace 列表
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        SELECT * FROM traces 
                        WHERE session_id = ? 
                        ORDER BY start_time DESC
                    """, (session_id,))
                    
                    rows = cursor.fetchall()
                    return [self._row_to_dict(row) for row in rows]
            except Exception as e:
                logger.error(f"获取会话 Trace 失败: {e}")
                return []
    
    def get_recent_traces(self, limit: int = 50, hours: int = 24) -> List[Dict[str, Any]]:
        """获取最近的 Trace
        
        Args:
            limit: 返回数量限制
            hours: 时间范围（小时）
        
        Returns:
            Trace 列表
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    start_time_threshold = (datetime.now() - timedelta(hours=hours)).timestamp()
                    
                    cursor.execute("""
                        SELECT * FROM traces 
                        WHERE start_time >= ? 
                        ORDER BY start_time DESC 
                        LIMIT ?
                    """, (start_time_threshold, limit))
                    
                    rows = cursor.fetchall()
                    return [self._row_to_dict(row) for row in rows]
            except Exception as e:
                logger.error(f"获取最近 Trace 失败: {e}")
                return []
    
    def get_error_traces(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取错误状态的 Trace
        
        Args:
            limit: 返回数量限制
        
        Returns:
            Trace 列表
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        SELECT * FROM traces 
                        WHERE status = 'failed' 
                        ORDER BY start_time DESC 
                        LIMIT ?
                    """, (limit,))
                    
                    rows = cursor.fetchall()
                    return [self._row_to_dict(row) for row in rows]
            except Exception as e:
                logger.error(f"获取错误 Trace 失败: {e}")
                return []
    
    def get_trace_statistics(self, hours: int = 24) -> Dict[str, Any]:
        """获取 Trace 统计信息
        
        Args:
            hours: 统计时间范围（小时）
        
        Returns:
            统计数据字典
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    start_time_threshold = (datetime.now() - timedelta(hours=hours)).timestamp()
                    
                    cursor.execute("""
                        SELECT 
                            COUNT(*) as total_traces,
                            COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_traces,
                            COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_traces,
                            COUNT(CASE WHEN status = 'running' THEN 1 END) as running_traces,
                            AVG(duration_ms) as avg_duration,
                            MAX(duration_ms) as max_duration,
                            MIN(duration_ms) as min_duration
                        FROM traces 
                        WHERE start_time >= ?
                    """, (start_time_threshold,))
                    
                    row = cursor.fetchone()
                    
                    return {
                        'total_traces': row['total_traces'] or 0,
                        'completed_traces': row['completed_traces'] or 0,
                        'failed_traces': row['failed_traces'] or 0,
                        'running_traces': row['running_traces'] or 0,
                        'avg_duration_ms': row['avg_duration'] or 0,
                        'max_duration_ms': row['max_duration'] or 0,
                        'min_duration_ms': row['min_duration'] or 0,
                        'time_range_hours': hours
                    }
            except Exception as e:
                logger.error(f"获取 Trace 统计失败: {e}")
                return {}
    
    def cleanup_old_traces(self, days: int = 30) -> int:
        """清理旧的 Trace 数据
        
        Args:
            days: 保留天数
        
        Returns:
            删除的记录数
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    start_time_threshold = (datetime.now() - timedelta(days=days)).timestamp()
                    
                    cursor.execute("""
                        DELETE FROM trace_logs 
                        WHERE timestamp < ?
                    """, (start_time_threshold,))
                    
                    deleted_logs = cursor.rowcount
                    
                    cursor.execute("""
                        DELETE FROM traces 
                        WHERE start_time < ?
                    """, (start_time_threshold,))
                    
                    deleted_traces = cursor.rowcount
                    
                    conn.commit()
                    
                    return deleted_traces + deleted_logs
            except Exception as e:
                logger.error(f"清理旧 Trace 失败: {e}")
                return 0
    
    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        data = {
            'id': row['id'],
            'trace_id': row['trace_id'],
            'span_id': row['span_id'],
            'parent_span_id': row['parent_span_id'],
            'session_id': row['session_id'],
            'operation': row['operation'],
            'start_time': row['start_time'],
            'duration_ms': row['duration_ms'],
            'status': row['status'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at']
        }
        
        if row['metadata']:
            try:
                data['metadata'] = json.loads(row['metadata'])
            except:
                data['metadata'] = {}
        
        return data
    
    def _log_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """将日志行转换为字典"""
        data = {
            'id': row['id'],
            'trace_id': row['trace_id'],
            'span_id': row['span_id'],
            'level': row['log_level'],
            'message': row['log_message'],
            'timestamp': row['timestamp'],
            'created_at': row['created_at']
        }
        
        if row['log_data']:
            try:
                log_data = json.loads(row['log_data'])
                data.update(log_data)
            except:
                pass
        
        return data


_persistence_instance: Optional[TracePersistence] = None
_persistence_lock = threading.Lock()


def get_trace_persistence(db_path: Optional[str] = None) -> TracePersistence:
    """获取 Trace 持久化实例（单例）"""
    global _persistence_instance
    
    with _persistence_lock:
        if _persistence_instance is None:
            _persistence_instance = TracePersistence(db_path)
        
        return _persistence_instance