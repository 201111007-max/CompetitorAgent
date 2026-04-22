"""缓存管理模块 - 基于 SQLite 的高性能缓存系统"""

import sqlite3
import json
import hashlib
import time
import threading
import pickle
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List, Tuple
from datetime import datetime, timedelta
from functools import wraps

# 支持两种导入方式：包导入和直接运行
try:
    from ..core.config import CacheConfig
except ImportError:
    from core.config import CacheConfig


class CacheManager:
    """缓存管理器
    
    特性：
    - 基于 SQLite 数据库，高性能
    - 支持按天自动过期
    - 支持内存缓存 + SQLite 缓存两级缓存
    - 支持缓存键自动生成
    - 装饰器支持，简化使用
    - 线程安全
    - LRU 淘汰机制
    - 支持复杂查询
    """
    
    def __init__(
        self,
        cache_dir: str = "cache",
        ttl_hours: int = 24,
        max_size_mb: int = 100,
        max_items: int = 1000,
        enable_memory_cache: bool = True,
        db_name: str = "cache.db"
    ):
        """初始化缓存管理器
        
        Args:
            cache_dir: 缓存目录
            ttl_hours: 缓存过期时间（小时），默认 24 小时
            max_size_mb: 最大缓存大小（MB），默认 100MB
            max_items: 最大缓存项数量，默认 1000
            enable_memory_cache: 是否启用内存缓存，默认 True
            db_name: SQLite 数据库文件名，默认 cache.db
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.db_path = self.cache_dir / db_name
        self.ttl_hours = ttl_hours
        self.max_size_mb = max_size_mb
        self.max_items = max_items
        self.enable_memory_cache = enable_memory_cache
        
        # 线程安全
        self._lock = threading.RLock()
        
        # 内存缓存
        self._memory_cache: Dict[str, Any] = {}
        self._memory_timestamp: Dict[str, float] = {}
        self._memory_access_time: Dict[str, float] = {}  # 记录访问时间用于 LRU
        
        # 缓存统计
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
        }
        
        # 初始化 SQLite 数据库
        self._init_database()
    
    def _init_database(self) -> None:
        """初始化 SQLite 数据库"""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 创建缓存表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cache_items (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    access_count INTEGER DEFAULT 0,
                    last_access REAL,
                    size_bytes INTEGER NOT NULL
                )
            ''')
            
            # 创建索引以加速查询
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_timestamp ON cache_items(timestamp)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_last_access ON cache_items(last_access)
            ''')
            
            conn.commit()
            conn.close()
    
    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn
    
    @classmethod
    def from_config(cls, config: CacheConfig) -> "CacheManager":
        """从配置创建缓存管理器"""
        return cls(
            cache_dir=config.cache_dir,
            ttl_hours=config.ttl_hours,
            max_size_mb=config.max_size_mb,
            max_items=config.max_items,
            enable_memory_cache=config.enable_memory_cache,
        )
    
    def _get_cache_key(self, prefix: str, *args, **kwargs) -> str:
        """生成缓存键（使用更可靠的序列化方式）"""
        # 使用 pickle 序列化确保参数顺序无关
        key_obj = {
            "prefix": prefix,
            "args": args,
            "kwargs": sorted(kwargs.items()) if kwargs else {}
        }
        key_bytes = pickle.dumps(key_obj, protocol=pickle.HIGHEST_PROTOCOL)
        return hashlib.sha256(key_bytes).hexdigest()
    
    def _is_expired(self, timestamp: float) -> bool:
        """检查缓存是否过期"""
        if timestamp == 0:
            return True
        elapsed = time.time() - timestamp
        return elapsed > (self.ttl_hours * 3600)
    
    def _update_access_time(self, cache_key: str) -> None:
        """更新缓存项的访问时间"""
        self._memory_access_time[cache_key] = time.time()
    
    def _evict_if_needed(self) -> None:
        """如果超过限制，淘汰最旧的缓存（LRU）"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # 检查数量限制
            cursor.execute("SELECT COUNT(*) FROM cache_items")
            count = cursor.fetchone()[0]
            
            # 检查大小限制
            cursor.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM cache_items")
            total_size = cursor.fetchone()[0]
            max_size_bytes = self.max_size_mb * 1024 * 1024
            
            # 淘汰最旧的缓存
            while count > self.max_items or total_size > max_size_bytes:
                # 删除最久未访问的记录
                cursor.execute('''
                    DELETE FROM cache_items 
                    WHERE key = (
                        SELECT key FROM cache_items 
                        ORDER BY last_access ASC 
                        LIMIT 1
                    )
                ''')
                
                if cursor.rowcount == 0:
                    break
                
                count -= 1
                cursor.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM cache_items")
                total_size = cursor.fetchone()[0]
                self._stats["evictions"] += 1
            
            conn.commit()
        finally:
            conn.close()
    
    def get(self, cache_key: str) -> Optional[Any]:
        """获取缓存
        
        优先级：内存缓存 > SQLite 缓存
        线程安全
        """
        with self._lock:
            # 1. 检查内存缓存
            if self.enable_memory_cache and cache_key in self._memory_cache:
                if not self._is_expired(self._memory_timestamp.get(cache_key, 0)):
                    self._update_access_time(cache_key)
                    self._stats["hits"] += 1
                    return self._memory_cache[cache_key]
                else:
                    # 内存缓存过期，清理
                    del self._memory_cache[cache_key]
                    del self._memory_timestamp[cache_key]
                    self._memory_access_time.pop(cache_key, None)
            
            # 2. 检查 SQLite 缓存
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT value, timestamp FROM cache_items 
                    WHERE key = ?
                ''', (cache_key,))
                
                row = cursor.fetchone()
                if row:
                    value_str = row["value"]
                    timestamp = row["timestamp"]
                    
                    # 检查是否过期
                    if not self._is_expired(timestamp):
                        # 反序列化数据
                        try:
                            data = json.loads(value_str)
                        except json.JSONDecodeError:
                            data = pickle.loads(eval(value_str))
                        
                        # 加载到内存缓存
                        if self.enable_memory_cache:
                            self._memory_cache[cache_key] = data
                            self._memory_timestamp[cache_key] = timestamp
                            self._update_access_time(cache_key)
                        
                        # 更新访问统计
                        cursor.execute('''
                            UPDATE cache_items 
                            SET access_count = access_count + 1, last_access = ?
                            WHERE key = ?
                        ''', (time.time(), cache_key))
                        conn.commit()
                        
                        self._stats["hits"] += 1
                        return data
                    else:
                        # 缓存过期，删除
                        cursor.execute('DELETE FROM cache_items WHERE key = ?', (cache_key,))
                        conn.commit()
                        self._stats["evictions"] += 1
            finally:
                conn.close()
            
            self._stats["misses"] += 1
            return None
    
    def set(self, cache_key: str, data: Any) -> None:
        """设置缓存
        
        线程安全，自动淘汰
        """
        with self._lock:
            timestamp = time.time()
            
            # 1. 保存到内存缓存
            if self.enable_memory_cache:
                self._memory_cache[cache_key] = data
                self._memory_timestamp[cache_key] = timestamp
                self._update_access_time(cache_key)
            
            # 2. 保存到 SQLite 缓存
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # 序列化数据
                try:
                    value_str = json.dumps(data, ensure_ascii=False)
                except (TypeError, ValueError):
                    # 如果不能 JSON 序列化，使用 pickle
                    value_str = repr(pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL))
                
                # 计算大小
                size_bytes = len(value_str.encode('utf-8'))
                
                # 使用 INSERT OR REPLACE
                cursor.execute('''
                    INSERT OR REPLACE INTO cache_items 
                    (key, value, timestamp, created_at, access_count, last_access, size_bytes)
                    VALUES (?, ?, ?, ?, 0, ?, ?)
                ''', (
                    cache_key,
                    value_str,
                    timestamp,
                    datetime.now().isoformat(),
                    time.time(),
                    size_bytes
                ))
                
                conn.commit()
            finally:
                conn.close()
            
            # 3. 检查是否需要淘汰
            self._evict_if_needed()
    
    def delete(self, cache_key: str) -> bool:
        """删除指定缓存
        
        Returns:
            bool: 是否成功删除
        """
        with self._lock:
            # 清理内存缓存
            self._memory_cache.pop(cache_key, None)
            self._memory_timestamp.pop(cache_key, None)
            self._memory_access_time.pop(cache_key, None)
            
            # 清理 SQLite 缓存
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM cache_items WHERE key = ?', (cache_key,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()
    
    def exists(self, cache_key: str) -> bool:
        """检查缓存是否存在
        
        Returns:
            bool: 是否存在
        """
        with self._lock:
            # 检查内存缓存
            if self.enable_memory_cache and cache_key in self._memory_cache:
                if not self._is_expired(self._memory_timestamp.get(cache_key, 0)):
                    return True
            
            # 检查 SQLite 缓存
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT timestamp FROM cache_items WHERE key = ?
                ''', (cache_key,))
                
                row = cursor.fetchone()
                if row:
                    timestamp = row["timestamp"]
                    if not self._is_expired(timestamp):
                        return True
                    else:
                        # 过期，删除
                        cursor.execute('DELETE FROM cache_items WHERE key = ?', (cache_key,))
                        conn.commit()
                        self._stats["evictions"] += 1
                
                return False
            finally:
                conn.close()
    
    def clear(self) -> None:
        """清空所有缓存"""
        with self._lock:
            # 清空内存缓存
            self._memory_cache.clear()
            self._memory_timestamp.clear()
            self._memory_access_time.clear()
            
            # 清空 SQLite 缓存
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM cache_items')
                conn.commit()
            finally:
                conn.close()
            
            # 重置统计
            self._stats = {"hits": 0, "misses": 0, "evictions": 0}
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # 获取基本信息
                cursor.execute("SELECT COUNT(*) as count, COALESCE(SUM(size_bytes), 0) as total_size FROM cache_items")
                row = cursor.fetchone()
                item_count = row["count"]
                total_size = row["total_size"]
                
                # 计算命中率
                total_requests = self._stats["hits"] + self._stats["misses"]
                hit_rate = (self._stats["hits"] / total_requests * 100) if total_requests > 0 else 0.0
                
                return {
                    "hits": self._stats["hits"],
                    "misses": self._stats["misses"],
                    "evictions": self._stats["evictions"],
                    "hit_rate": f"{hit_rate:.2f}%",  # 字符串格式
                    "hit_rate_float": hit_rate,  # 数字格式
                    "item_count": item_count,
                    "total_size_bytes": total_size,
                    "total_size_mb": f"{total_size / (1024 * 1024):.2f} MB",
                    "memory_cache_items": len(self._memory_cache)
                }
            finally:
                conn.close()
    
    def reset_stats(self) -> None:
        """重置统计信息"""
        with self._lock:
            self._stats = {"hits": 0, "misses": 0, "evictions": 0}
    
    def cleanup_expired(self) -> int:
        """清理所有过期的缓存
        
        Returns:
            int: 清理的缓存数量
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # 计算过期时间戳
                expired_timestamp = time.time() - (self.ttl_hours * 3600)
                
                # 删除过期记录
                cursor.execute('''
                    DELETE FROM cache_items 
                    WHERE timestamp < ?
                ''', (expired_timestamp,))
                
                deleted_count = cursor.rowcount
                conn.commit()
                
                return deleted_count
            finally:
                conn.close()
    
    def get_all_keys(self) -> List[str]:
        """获取所有缓存键
        
        Returns:
            List[str]: 缓存键列表
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT key FROM cache_items")
                return [row["key"] for row in cursor.fetchall()]
            finally:
                conn.close()
    
    def cached(self, prefix: str = "", ttl_hours: Optional[int] = None):
        """缓存装饰器
        
        Args:
            prefix: 缓存键前缀
            ttl_hours: 自定义过期时间（可选）
            
        Usage:
            @cache_manager.cached(prefix="hero_matchup")
            def get_matchup(hero_id: int):
                return expensive_operation(hero_id)
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                # 生成缓存键
                cache_key = self._get_cache_key(prefix or func.__name__, *args, **kwargs)
                
                # 尝试获取缓存
                cached_result = self.get(cache_key)
                if cached_result is not None:
                    return cached_result
                
                # 执行函数
                result = func(*args, **kwargs)
                
                # 保存缓存
                if result is not None:
                    self.set(cache_key, result)
                
                return result
            return wrapper
        return decorator


# 全局缓存实例（单例模式）
_cache_instance: Optional[CacheManager] = None


def get_cache(cache_dir: str = "cache", **kwargs) -> CacheManager:
    """获取全局缓存实例（单例）"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = CacheManager(cache_dir=cache_dir, **kwargs)
    return _cache_instance
