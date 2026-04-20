"""OpenDota API 客户端封装"""

import os
import requests
import json
from typing import Dict, List, Optional, Any
from pathlib import Path
import time

from ..cache.cache_manager import CacheManager
from ..core.config import AgentConfig, RateLimitConfig, CacheConfig


class OpenDotaClient:
    """OpenDota API 客户端
    
    特性：
    - 自动速率限制（默认 1 秒/请求，符合 60 次/分钟限制）
    - 智能缓存系统（内存 + 文件两级缓存，默认 24 小时过期）
    - 英雄数据自动缓存
    - 支持缓存预热
    """

    BASE_URL = "https://api.opendota.com/api"

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: Optional[str] = None,
        rate_limit_delay: float = 1.0,
        cache_ttl_hours: int = 24,
        config: Optional[AgentConfig] = None
    ):
        """初始化客户端
        
        Args:
            api_key: OpenDota API Key（可选，可提升限制）
            cache_dir: 缓存目录（默认：模块目录下的 cache）
            rate_limit_delay: 请求间隔（秒），默认 1.0（60 次/分钟）
            cache_ttl_hours: 缓存过期时间（小时），默认 24
            config: 配置对象（可选，优先级高于其他参数）
        """
        # 使用配置对象或创建默认配置
        if config:
            self.config = config
            self.api_key = config.api_key or api_key
            rate_config = config.rate_limit
            cache_config = config.cache
        else:
            self.config = None
            self.api_key = api_key
            rate_config = RateLimitConfig(delay_seconds=rate_limit_delay)
            cache_config = CacheConfig(cache_dir=cache_dir, ttl_hours=cache_ttl_hours)
        
        self.session = requests.Session()
        self.rate_limit_delay = rate_config.delay_seconds
        self._last_request_time = 0
        
        # 初始化缓存管理器
        cache_path = cache_dir or cache_config.cache_dir
        if not os.path.isabs(cache_path):
            cache_path = str(Path(__file__).parent.parent / cache_path)
        
        self.cache = CacheManager.from_config(cache_config) if config else CacheManager(
            cache_dir=cache_path,
            ttl_hours=cache_config.ttl_hours,
            max_size_mb=cache_config.max_size_mb,
            max_items=cache_config.max_items,
        )
        
        # 英雄列表内存缓存（常用数据）
        self._heroes_cache: Optional[List[Dict]] = None

    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        """发送 API 请求（带速率限制）"""
        # 速率限制：确保请求间隔
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)

        url = f"{self.BASE_URL}{endpoint}"
        request_params = params or {}
        if self.api_key:
            request_params["api_key"] = self.api_key

        try:
            timeout = self.config.rate_limit.timeout_seconds if self.config else 10
            response = self.session.get(url, params=request_params, timeout=timeout)
            self._last_request_time = time.time()
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"API 请求失败：{e}")
            return None

    def get_heroes(self, use_cache: bool = True) -> List[Dict]:
        """获取所有英雄列表（带缓存）"""
        # 优先内存缓存
        if use_cache and self._heroes_cache:
            return self._heroes_cache
        
        # 使用缓存管理器
        cache_key = "heroes_list"
        cached = self.cache.get(cache_key) if use_cache else None
        if cached:
            self._heroes_cache = cached
            return cached

        # API 请求
        heroes = self._make_request("/heroes")
        if heroes:
            self._heroes_cache = heroes
            if use_cache:
                self.cache.set(cache_key, heroes)
        return heroes or []

    def get_hero_matchups(self, hero_id: int, use_cache: bool = True) -> Optional[List[Dict]]:
        """获取英雄克制关系数据（带缓存）"""
        cache_key = f"hero_matchups_{hero_id}"
        
        # 尝试缓存
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        
        # API 请求
        result = self._make_request(f"/heroes/{hero_id}/matchups")
        if result is not None and use_cache:
            self.cache.set(cache_key, result)
        return result

    def get_hero_item_popularity(self, hero_id: int, use_cache: bool = True) -> Optional[Dict]:
        """获取英雄物品 popularity 数据（带缓存）"""
        cache_key = f"hero_items_{hero_id}"
        
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        
        result = self._make_request(f"/heroes/{hero_id}/itemPopularity")
        if result is not None and use_cache:
            self.cache.set(cache_key, result)
        return result

    def get_hero_stats(self, use_cache: bool = True) -> Optional[List[Dict]]:
        """获取英雄统计数据（带缓存）"""
        cache_key = "hero_stats"
        
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        
        result = self._make_request("/heroStats")
        if result is not None and use_cache:
            self.cache.set(cache_key, result)
        return result

    def get_item_timings(self, use_cache: bool = True) -> Optional[List[Dict]]:
        """获取物品购买时机数据（带缓存）"""
        cache_key = "item_timings"
        
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        
        result = self._make_request("/scenarios/itemTimings")
        if result is not None and use_cache:
            self.cache.set(cache_key, result)
        return result

    def warm_up_cache(self, hero_ids: Optional[List[int]] = None) -> None:
        """预热缓存
        
        Args:
            hero_ids: 要预热的英雄 ID 列表（可选，默认使用配置中的热门英雄）
        """
        print("正在预热缓存...")
        
        # 加载英雄列表
        print("  - 加载英雄列表...")
        self.get_heroes()
        
        # 确定要预热的英雄
        if hero_ids:
            heroes_to_warm = hero_ids
        elif self.config:
            heroes_to_warm = self.config.popular_heroes
        else:
            # 默认热门英雄
            heroes_to_warm = [1, 2, 5, 10, 15, 20, 25, 30, 35, 40]
        
        # 预热英雄数据
        print(f"  - 预热 {len(heroes_to_warm)} 个热门英雄数据...")
        for hero_id in heroes_to_warm:
            self.get_hero_matchups(hero_id)
            self.get_hero_item_popularity(hero_id)
        
        print("✅ 缓存预热完成")

    def hero_name_to_id(self, hero_name: str) -> Optional[int]:
        """将英雄名称转换为 ID
        
        Args:
            hero_name: 英雄名称（支持 localized_name 或 name）
            
        Returns:
            英雄 ID，未找到返回 None
        """
        heroes = self.get_heroes()
        hero_name_lower = hero_name.lower()
        
        for hero in heroes:
            # 匹配 localized_name（显示名称）
            if hero.get("localized_name", "").lower() == hero_name_lower:
                return hero["id"]
            # 匹配 name（内部名称，如 npc_dota_hero_antimage）
            if hero.get("name", "").lower().replace("npc_dota_hero_", "") == hero_name_lower:
                return hero["id"]
        
        return None

    def hero_id_to_name(self, hero_id: int) -> str:
        """将英雄 ID 转换为名称
        
        Args:
            hero_id: 英雄 ID
            
        Returns:
            英雄名称，未找到返回 "Unknown"
        """
        heroes = self.get_heroes()
        
        for hero in heroes:
            if hero["id"] == hero_id:
                return hero.get("localized_name", "Unknown")
        
        return "Unknown"
