"""缓存管理模块 - 支持每日自动更新的缓存系统"""

import json
import hashlib
import time
import threading
import pickle
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List, Tuple
from datetime import datetime, timedelta
from functools import wraps

from ..core.config import CacheConfig


class CacheManager:
    """缓存管理器
    
    特性：
    - 支持按天自动过期
    - 支持内存缓存 + 文件缓存两级缓存
    - 支持缓存键自动生成
    - 装饰器支持，简化使用
    - 线程安全
    - LRU 淘汰机制
    """
    
    def __init__(
        self,
        cache_dir: str = "cache",
        ttl_hours: int = 24,
        max_size_mb: int = 100,
        max_items: int = 1000,
        enable_memory_cache: bool = True
    ):
        """初始化缓存管理器
        
        Args:
            cache_dir: 缓存目录
            ttl_hours: 缓存过期时间（小时），默认 24 小时
            max_size_mb: 最大缓存大小（MB），默认 100MB
            max_items: 最大缓存项数量，默认 1000
            enable_memory_cache: 是否启用内存缓存，默认 True
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
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
    
    def _get_cache_file(self, cache_key: str) -> Path:
        """获取缓存文件路径"""
        return self.cache_dir / f"{cache_key}.json"
    
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
        # 检查数量限制
        cache_files = [
            (f.stat().st_mtime, f)
            for f in self.cache_dir.glob("*.json")
        ]
        
        # 按大小检查
        total_size = sum(f.stat().st_size for _, f in cache_files)
        max_size_bytes = self.max_size_mb * 1024 * 1024
        
        # 淘汰最旧的文件直到满足限制
        cache_files.sort()  # 按修改时间排序
        
        while (len(cache_files) > self.max_items or total_size > max_size_bytes) and cache_files:
            _, oldest_file = cache_files.pop(0)
            try:
                oldest_file.unlink()
                self._stats["evictions"] += 1
                total_size -= oldest_file.stat().st_size if oldest_file.exists() else 0
            except Exception:
                pass
    
    def get(self, cache_key: str) -> Optional[Any]:
        """获取缓存
        
        优先级：内存缓存 > 文件缓存
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
            
            # 2. 检查文件缓存
            cache_file = self._get_cache_file(cache_key)
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    # 检查文件缓存是否过期
                    if not self._is_expired(data.get("_timestamp", 0)):
                        # 加载到内存缓存
                        if self.enable_memory_cache:
                            self._memory_cache[cache_key] = data.get("_data")
                            self._memory_timestamp[cache_key] = data.get("_timestamp")
                            self._update_access_time(cache_key)
                        
                        self._stats["hits"] += 1
                        return data.get("_data")
                    else:
                        # 文件缓存过期，删除
                        cache_file.unlink()
                        self._stats["evictions"] += 1
                except (json.JSONDecodeError, KeyError):
                    # 缓存文件损坏，删除
                    cache_file.unlink()
            
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
            
            # 2. 保存到文件缓存
            cache_file = self._get_cache_file(cache_key)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({
                    "_data": data,
                    "_timestamp": timestamp,
                    "_created": datetime.now().isoformat()
                }, f, ensure_ascii=False, indent=2)
            
            # 3. 检查是否需要淘汰
            self._evict_if_needed()
    
    def clear(self) -> None:
        """清空所有缓存"""
        with self._lock:
            # 清空内存缓存
            self._memory_cache.clear()
            self._memory_timestamp.clear()
            self._memory_access_time.clear()
            
            # 清空文件缓存
            for cache_file in self.cache_dir.glob("*.json"):
                try:
                    cache_file.unlink()
                except Exception:
                    pass
            
            # 重置统计
            self._stats = {"hits": 0, "misses": 0, "evictions": 0}
    
    def get_stats(self) -> Dict[str, int]:
        """获取缓存统计"""
        with self._lock:
            return self._stats.copy()
    
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
