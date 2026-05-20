"""OpenDota API 客户端封装"""

import os
import requests
import json
from typing import Dict, List, Optional, Any
from pathlib import Path
import time

from utils.log_config import get_logger

# Langfuse 监控（可选）
try:
    from utils.langfuse_adapter import LangfuseClient
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    LangfuseClient = None

logger = get_logger("api_client", component="utils")

# 支持两种导入方式：包导入和直接运行
try:
    from ..cache.cache_manager import CacheManager
    from ..core.config import AgentConfig, RateLimitConfig, CacheConfig
    from ..utils.localization import DotaLocalizer
except ImportError:
    from cache.cache_manager import CacheManager
    from core.config import AgentConfig, RateLimitConfig, CacheConfig
    from utils.localization import DotaLocalizer


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
            cache_config = CacheConfig(ttl_hours=cache_ttl_hours)
        
        self.session = requests.Session()
        self.rate_limit_delay = rate_config.delay_seconds
        self._last_request_time = 0

        # 初始化缓存管理器
        if config:
            self.cache = CacheManager.from_config(cache_config)
        else:
            cache_path = cache_dir or cache_config.cache_dir
            if not os.path.isabs(cache_path):
                cache_path = str(Path(__file__).parent.parent / cache_path)
            self.cache = CacheManager(
                cache_dir=cache_path,
                ttl_hours=cache_config.ttl_hours,
                max_size_mb=cache_config.max_size_mb,
                max_items=cache_config.max_items,
            )

        # 英雄列表内存缓存（常用数据）
        self._heroes_cache: Optional[List[Dict]] = None
        
        # 本地化工具实例
        self._localizer = DotaLocalizer()

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
            logger.error(f"API 请求失败：{e}")
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
        
        # 尝试从本地 JSON 文件加载（作为备用数据源）
        try:
            import json
            from pathlib import Path
            heroes_file = Path(__file__).parent.parent / "cache" / "heroes_list.json"
            if heroes_file.exists():
                with open(heroes_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and '_data' in data:
                        heroes = data['_data']
                    else:
                        heroes = data
                    if heroes and len(heroes) > 10:
                        self._heroes_cache = heroes
                        if use_cache:
                            self.cache.set(cache_key, heroes)
                        return heroes
        except Exception as e:
            logger.error(f"从本地文件加载英雄列表失败: {e}")
        
        # API 请求
        heroes = self._make_request("/heroes")
        if heroes:
            self._heroes_cache = heroes
            if use_cache:
                self.cache.set(cache_key, heroes)
        return heroes or []

    def get_hero_matchups(self, hero_id: int, use_cache: bool = True) -> Optional[List[Dict]]:
        """获取英雄克制关系数据（带缓存）"""
        # 获取 Langfuse 客户端
        langfuse_client = LangfuseClient.get_instance() if LANGFUSE_AVAILABLE else None
        
        # 创建 Langfuse Span（如果启用）
        if langfuse_client and langfuse_client.enabled:
            from utils.langfuse_adapter import NoOpTrace
            trace = NoOpTrace()
            span = trace.span(
                name="api_call_hero_matchups",
                metadata={"api": "opendota", "hero_id": hero_id}
            )
        else:
            from utils.langfuse_adapter import NoOpSpan
            span = NoOpSpan()
        
        with span:
            cache_key = f"hero_matchups_{hero_id}"
            
            # 尝试缓存
            if use_cache:
                cached = self.cache.get(cache_key)
                if cached is not None:
                    span.update(metadata={"cache_hit": True})
                    return cached
            
            # API 请求
            result = self._make_request(f"/heroes/{hero_id}/matchups")
            if result is not None and use_cache:
                self.cache.set(cache_key, result)
            
            span.update(output={"result_type": type(result).__name__})
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

    def get_constants(self, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """获取游戏常量数据（物品、英雄等）（带缓存）

        Returns:
            Dict: 包含 items, heroes 等常量数据
        """
        cache_key = "game_constants"

        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        result = self._make_request("/constants")
        if result is not None and use_cache:
            self.cache.set(cache_key, result)
        return result

    def warm_up_cache(self, hero_ids: Optional[List[int]] = None, full_warmup: bool = False) -> None:
        """预热缓存
        
        Args:
            hero_ids: 要预热的英雄 ID 列表（可选，默认使用配置中的热门英雄）
            full_warmup: 是否全量预热所有英雄数据（默认 False）
        """
        logger.info("正在预热缓存...")
        
        # 加载英雄列表
        logger.info("  - 加载英雄列表...")
        all_heroes = self.get_heroes()
        
        # 确定要预热的英雄
        if full_warmup:
            # 全量预热：获取所有英雄 ID
            heroes_to_warm = [hero["id"] for hero in all_heroes]
            logger.info(f"  - 全量预热模式：共 {len(heroes_to_warm)} 个英雄")
        elif hero_ids:
            heroes_to_warm = hero_ids
        elif self.config:
            heroes_to_warm = self.config.popular_heroes
        else:
            # 默认热门英雄
            heroes_to_warm = [1, 2, 5, 10, 15, 20, 25, 30, 35, 40]
        
        # 预热英雄数据
        logger.info(f"  - 预热 {len(heroes_to_warm)} 个英雄数据...")
        success_count = 0
        fail_count = 0
        
        for i, hero_id in enumerate(heroes_to_warm, 1):
            try:
                if i % 10 == 0:
                    logger.info(f"    进度: {i}/{len(heroes_to_warm)}")
                
                matchup_result = self.get_hero_matchups(hero_id)
                if matchup_result is not None:
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                logger.warning(f"    警告: 英雄 {hero_id} 预热失败: {e}")
                fail_count += 1
        
        logger.info(f"缓存预热完成: 成功 {success_count} 个, 失败 {fail_count} 个")

    def hero_name_to_id(self, hero_name: str) -> Optional[int]:
        """将英雄名称转换为 ID
        
        Args:
            hero_name: 英雄名称（支持中文名、localized_name、内部名称、下划线格式等）
            
        Returns:
            英雄 ID，未找到返回 None
        """
        heroes = self.get_heroes()
        hero_name_lower = hero_name.lower().strip()
        
        # 1. 优先尝试中文名称匹配
        for hero_id_str, name_data in self._localizer._heroes_cn.items():
            if name_data.get('cn') == hero_name or name_data.get('cn').lower() == hero_name_lower:
                hero_id = int(hero_id_str)
                return hero_id
        
        for hero in heroes:
            # 2. 匹配 localized_name（显示名称，如 "Faceless Void"）
            if hero.get("localized_name", "").lower() == hero_name_lower:
                return hero["id"]
            
            # 3. 匹配内部名称（如 "npc_dota_hero_faceless_void"）
            if hero.get("name", "").lower() == hero_name_lower:
                return hero["id"]
            
            # 4. 匹配去掉 "npc_dota_hero_" 前缀的名称（如 "faceless_void"）
            internal_name = hero.get("name", "").lower().replace("npc_dota_hero_", "")
            if internal_name == hero_name_lower:
                return hero["id"]
            
            # 5. 匹配空格替换为下划线的 localized_name（如 "faceless_void" 匹配 "Faceless Void"）
            localized_lower = hero.get("localized_name", "").lower()
            if localized_lower.replace(" ", "_") == hero_name_lower:
                return hero["id"]
            
            # 6. 匹配去掉连字符的名称（如 "anti-mage" 匹配 "antimage"）
            if hero_name_lower.replace("-", "").replace("_", "") == internal_name.replace("-", "").replace("_", ""):
                return hero["id"]
            
            # 7. 模糊匹配：检查 hero_name 是否是内部名称的一部分
            if hero_name_lower in internal_name or internal_name in hero_name_lower:
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
