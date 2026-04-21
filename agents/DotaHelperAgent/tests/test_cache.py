"""缓存模块完整测试 - 包括功能测试和性能测试"""

import pytest
import os
import tempfile
import shutil
import time
import threading
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from cache.cache_manager import CacheManager


class TestCacheManagerBasic:
    """缓存管理器基础功能测试"""
    
    @pytest.fixture
    def temp_cache_dir(self):
        """创建临时目录用于测试"""
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)
    
    @pytest.fixture
    def cache_manager(self, temp_cache_dir):
        """创建缓存管理器实例"""
        return CacheManager(
            cache_dir=temp_cache_dir,
            ttl_hours=1,
            enable_memory_cache=True
        )
    
    def test_basic_set_get(self, cache_manager):
        """测试基本的设置和获取功能"""
        data = {"key": "value", "number": 42}
        cache_manager.set("test_key", data)
        
        assert cache_manager.get("test_key") is not None
        assert cache_manager.get("test_key")["key"] == "value"
        assert cache_manager.get("test_key")["number"] == 42
    
    def test_get_nonexistent_key(self, cache_manager):
        """测试获取不存在的键"""
        assert cache_manager.get("nonexistent_key") is None
    
    def test_set_with_different_types(self, cache_manager):
        """测试设置不同类型的数据"""
        test_data = [
            ("string_key", "string_value"),
            ("int_key", 42),
            ("float_key", 3.14),
            ("list_key", [1, 2, 3]),
            ("dict_key", {"nested": "value"}),
            ("tuple_key", (1, 2, 3)),
            ("none_key", None),
        ]
        
        for key, value in test_data:
            cache_manager.set(key, value)
            assert cache_manager.get(key) == value
    
    def test_clear_cache(self, cache_manager):
        """测试清空缓存"""
        cache_manager.set("key1", "value1")
        cache_manager.set("key2", "value2")
        cache_manager.set("key3", "value3")
        
        cache_manager.clear()
        
        assert cache_manager.get("key1") is None
        assert cache_manager.get("key2") is None
        assert cache_manager.get("key3") is None
    
    def test_delete_key(self, cache_manager):
        """测试删除指定键"""
        cache_manager.set("key1", "value1")
        cache_manager.set("key2", "value2")
        
        cache_manager.delete("key1")
        
        assert cache_manager.get("key1") is None
        assert cache_manager.get("key2") == "value2"
    
    def test_exists(self, cache_manager):
        """测试检查键是否存在"""
        cache_manager.set("existing_key", "value")
        
        assert cache_manager.exists("existing_key") is True
        assert cache_manager.exists("nonexistent_key") is False


class TestCacheExpiration:
    """缓存过期测试"""
    
    @pytest.fixture
    def temp_cache_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)
    
    def test_cache_expiration(self, temp_cache_dir):
        """测试缓存过期"""
        with patch('time.time') as mock_time:
            mock_time.return_value = 100
            
            manager = CacheManager(
                cache_dir=temp_cache_dir,
                ttl_hours=1,
                enable_memory_cache=False
            )
            
            manager.set("test_key", "value")
            
            assert manager.get("test_key") == "value"
            
            mock_time.return_value = 100 + 3600 + 1
            
            assert manager.get("test_key") is None
    
    def test_cache_not_expired(self, temp_cache_dir):
        """测试缓存未过期"""
        with patch('time.time') as mock_time:
            mock_time.return_value = 100
            
            manager = CacheManager(
                cache_dir=temp_cache_dir,
                ttl_hours=24,
                enable_memory_cache=False
            )
            
            manager.set("test_key", "value")
            
            mock_time.return_value = 100 + 3600
            
            assert manager.get("test_key") == "value"


class TestLRUEviction:
    """LRU 淘汰机制测试"""
    
    @pytest.fixture
    def temp_cache_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)
    
    def test_lru_eviction_by_items(self, temp_cache_dir):
        """测试基于数量的 LRU 淘汰"""
        manager = CacheManager(
            cache_dir=temp_cache_dir,
            ttl_hours=24,
            max_items=3,
            enable_memory_cache=False
        )
        
        for i in range(5):
            manager.set(f"key_{i}", f"value_{i}")
        
        cache_files = list(Path(temp_cache_dir).glob("*.json"))
        assert len(cache_files) <= 3
    
    def test_lru_eviction_by_size(self, temp_cache_dir):
        """测试基于大小的 LRU 淘汰"""
        manager = CacheManager(
            cache_dir=temp_cache_dir,
            ttl_hours=24,
            max_size_mb=1,
            max_items=1000,
            enable_memory_cache=False
        )
        
        large_data = {"data": "x" * 100000}
        
        for i in range(10):
            manager.set(f"large_key_{i}", large_data)
        
        cache_files = list(Path(temp_cache_dir).glob("*.json"))
        total_size = sum(f.stat().st_size for f in cache_files)
        
        assert total_size <= 1 * 1024 * 1024


class TestMemoryCache:
    """内存缓存测试"""
    
    @pytest.fixture
    def temp_cache_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)
    
    def test_memory_cache_priority(self, temp_cache_dir):
        """测试内存缓存优先级高于文件缓存"""
        manager = CacheManager(
            cache_dir=temp_cache_dir,
            ttl_hours=24,
            enable_memory_cache=True
        )
        
        manager.set("test_key", "value1")
        
        assert manager.get("test_key") == "value1"
        
        manager._memory_cache.clear()
        
        assert manager.get("test_key") == "value1"
    
    def test_memory_cache_disabled(self, temp_cache_dir):
        """测试禁用内存缓存"""
        manager = CacheManager(
            cache_dir=temp_cache_dir,
            ttl_hours=24,
            enable_memory_cache=False
        )
        
        manager.set("test_key", "value")
        
        assert len(manager._memory_cache) == 0
        
        cache_files = list(Path(temp_cache_dir).glob("*.json"))
        assert len(cache_files) > 0


class TestCacheStats:
    """缓存统计测试"""
    
    @pytest.fixture
    def temp_cache_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)
    
    def test_stats_tracking(self, temp_cache_dir):
        """测试统计信息跟踪"""
        manager = CacheManager(
            cache_dir=temp_cache_dir,
            ttl_hours=24,
            enable_memory_cache=True
        )
        
        initial_stats = manager.get_stats()
        
        manager.set("key1", "value1")
        manager.get("key1")
        manager.get("key1")
        manager.get("nonexistent")
        
        updated_stats = manager.get_stats()
        
        assert updated_stats["hits"] >= 2
        assert updated_stats["misses"] >= 1
        assert updated_stats["hit_rate"] > 0
    
    def test_reset_stats(self, temp_cache_dir):
        """测试重置统计"""
        manager = CacheManager(
            cache_dir=temp_cache_dir,
            ttl_hours=24,
            enable_memory_cache=True
        )
        
        manager.set("key1", "value1")
        manager.get("key1")
        
        manager.reset_stats()
        
        stats = manager.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0


class TestThreadSafety:
    """线程安全测试"""
    
    @pytest.fixture
    def temp_cache_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)
    
    def test_concurrent_access(self, temp_cache_dir):
        """测试并发访问"""
        manager = CacheManager(
            cache_dir=temp_cache_dir,
            ttl_hours=24,
            enable_memory_cache=True
        )
        
        errors = []
        
        def worker(worker_id):
            try:
                for i in range(10):
                    key = f"worker_{worker_id}_key_{i}"
                    manager.set(key, f"value_{i}")
                    manager.get(key)
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        
        for t in threads:
            t.start()
        
        for t in threads:
            t.join()
        
        assert len(errors) == 0


class TestCacheDecorator:
    """缓存装饰器测试"""
    
    @pytest.fixture
    def temp_cache_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)
    
    def test_get_cache_decorator(self, temp_cache_dir):
        """测试 @get_cache 装饰器"""
        from cache.cache_manager import get_cache
        
        manager = CacheManager(
            cache_dir=temp_cache_dir,
            ttl_hours=24,
            enable_memory_cache=True
        )
        
        call_count = [0]
        
        @get_cache("test_prefix")
        def expensive_function(x, y):
            call_count[0] += 1
            return x + y
        
        result1 = expensive_function(manager, 1, 2)
        result2 = expensive_function(manager, 1, 2)
        
        assert result1 == 3
        assert result2 == 3
        assert call_count[0] == 1


class TestCachePerformance:
    """缓存性能测试"""
    
    @pytest.fixture
    def temp_cache_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)
    
    def test_memory_cache_performance(self, temp_cache_dir):
        """测试内存缓存性能"""
        memory_manager = CacheManager(
            cache_dir=temp_cache_dir,
            ttl_hours=24,
            enable_memory_cache=True
        )
        
        memory_manager.set("perf_key", {"data": "test"})
        
        start = time.time()
        for _ in range(1000):
            memory_manager.get("perf_key")
        memory_time = time.time() - start
        
        assert memory_time < 1.0
    
    def test_file_cache_performance(self, temp_cache_dir):
        """测试文件缓存性能"""
        file_manager = CacheManager(
            cache_dir=temp_cache_dir,
            ttl_hours=24,
            enable_memory_cache=False
        )
        
        file_manager.set("perf_key", {"data": "test"})
        
        start = time.time()
        for _ in range(100):
            file_manager.get("perf_key")
        file_time = time.time() - start
        
        assert file_time < 5.0
    
    def test_cache_warmup_benefit(self, temp_cache_dir):
        """测试缓存预热的好处"""
        manager = CacheManager(
            cache_dir=temp_cache_dir,
            ttl_hours=24,
            enable_memory_cache=True
        )
        
        test_data = {f"key_{i}": f"value_{i}" for i in range(100)}
        
        for key, value in test_data.items():
            manager.set(key, value)
        
        start = time.time()
        for key in test_data.keys():
            manager.get(key)
        warm_cache_time = time.time() - start
        
        manager.clear()
        
        for key, value in test_data.items():
            manager.set(key, value)
        
        manager._memory_cache.clear()
        
        start = time.time()
        for key in test_data.keys():
            manager.get(key)
        cold_cache_time = time.time() - start
        
        assert warm_cache_time < cold_cache_time
