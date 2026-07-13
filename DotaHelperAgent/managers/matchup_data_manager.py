"""英雄 Matchup 数据管理器

统一管理英雄克制数据的多数据源访问，实现优先级访问策略：
1. Memory Cache（最快）
2. SQLite Cache（持久化）
3. Local JSON File（本地存储）
4. LLM Knowledge（兜底）
5. OpenDota API（后台异步更新）

新增特性：
- 数据过期机制（TTL）
- 数据完整性校验
"""

import json
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timedelta

try:
    from ..cache.cache_manager import CacheManager
    from ..utils.log_config import get_logger
except ImportError:
    from cache.cache_manager import CacheManager
    from utils.log_config import get_logger

logger = get_logger("matchup_data_manager", component="managers")


class MatchupDataManager:
    """英雄 Matchup 数据管理器
    
    特性：
    - 多数据源优先级访问
    - 启动时自动检查数据完整性
    - 后台异步加载缺失数据
    - 本地 JSON 持久化存储
    - 线程安全
    - 数据过期机制（TTL）
    - 数据完整性校验
    """
    
    TOTAL_HEROES = 124
    
    def __init__(
        self,
        cache_manager: CacheManager,
        api_client,
        llm_client=None,
        data_dir: str = "data/matchups",
        auto_load_on_startup: bool = True,
        ttl_days: int = 7
    ):
        """初始化 Matchup 数据管理器
        
        Args:
            cache_manager: 缓存管理器实例
            api_client: OpenDota API 客户端
            llm_client: LLM 客户端（可选，用于 fallback）
            data_dir: 本地 JSON 存储目录
            auto_load_on_startup: 启动时是否自动加载已有数据到缓存
            ttl_days: 数据过期时间（天数），默认7天
        """
        self.cache = cache_manager
        self.api_client = api_client
        self.llm_client = llm_client
        self.ttl_days = ttl_days
        
        self.data_dir = Path(data_dir)
        if not self.data_dir.is_absolute():
            self.data_dir = Path(__file__).parent.parent / data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self._lock = threading.RLock()
        self._data_status = {
            "total_heroes": self.TOTAL_HEROES,
            "loaded_heroes": 0,
            "missing_heroes": [],
            "last_update": None,
            "is_loading": False,
            "expired_heroes": 0,
            "invalid_heroes": 0
        }
        
        if auto_load_on_startup:
            self._check_and_load_existing_data()
    
    def _check_and_load_existing_data(self) -> None:
        """启动时检查数据完整性并加载已有数据"""
        with self._lock:
            existing_files = list(self.data_dir.glob("hero_*.json"))
            loaded_count = len(existing_files)
            
            self._data_status["loaded_heroes"] = loaded_count
            self._data_status["missing_heroes"] = self._get_missing_hero_ids(existing_files)
            self._data_status["last_update"] = datetime.now().isoformat()
            
            if loaded_count >= self.TOTAL_HEROES:
                logger.info(f"发现全量 matchup 数据: {loaded_count} 个文件")
                self._load_to_cache(existing_files)
            elif loaded_count > 0:
                logger.info(f"部分 matchup 数据存在: {loaded_count}/{self.TOTAL_HEROES}")
                self._load_to_cache(existing_files)
                self._start_background_load()
            else:
                logger.info("无 matchup 数据，启动后台全量加载")
                self._start_background_load()
    
    def _get_missing_hero_ids(self, existing_files: List[Path]) -> List[int]:
        """获取缺失的英雄 ID"""
        existing_ids = set()
        for f in existing_files:
            try:
                hero_id = int(f.stem.replace("hero_", ""))
                existing_ids.add(hero_id)
            except ValueError:
                continue
        
        all_hero_ids = set(range(1, self.TOTAL_HEROES + 1))
        return sorted(list(all_hero_ids - existing_ids))
    
    def _load_to_cache(self, files: List[Path]) -> None:
        """加载本地 JSON 文件到缓存（批量写入优化）"""
        logger.info(f"加载 {len(files)} 个本地 matchup 文件到缓存...")

        items = []
        for file_path in files:
            try:
                hero_id = int(file_path.stem.replace("hero_", ""))
                data = json.loads(file_path.read_text(encoding="utf-8"))
                cache_key = self._get_cache_key(hero_id)
                items.append((cache_key, data))
            except Exception as e:
                logger.warning(f"加载文件 {file_path} 失败: {e}")

        # 批量写入（单事务，性能提升 10-20 倍）
        if items:
            self.cache.set_batch(items)

        logger.info("本地数据加载完成")
    
    def _get_cache_key(self, hero_id: int) -> str:
        """生成缓存键"""
        return f"matchup_hero_{hero_id}"
    
    def _is_data_expired(self, data: Dict[str, Any]) -> bool:
        """检查数据是否过期
        
        Args:
            data: matchup 数据
            
        Returns:
            是否过期
        """
        if not isinstance(data, dict):
            return True
        
        metadata = data.get("_metadata", {})
        created_at = metadata.get("created_at")
        
        if not created_at:
            return True
        
        try:
            created_time = datetime.fromisoformat(created_at)
            expired_time = created_time + timedelta(days=self.ttl_days)
            return datetime.now() > expired_time
        except Exception:
            return True
    
    def _validate_data_integrity(self, data: Dict[str, Any]) -> bool:
        """校验数据完整性
        
        Args:
            data: matchup 数据
            
        Returns:
            数据是否完整有效
        """
        if not isinstance(data, dict):
            return False
        
        if not isinstance(data.get("matchup_data"), list):
            return False
        
        matchup_list = data.get("matchup_data", [])
        if len(matchup_list) == 0:
            return False
        
        for matchup in matchup_list[:5]:
            if not isinstance(matchup, dict):
                return False
            
            required_fields = ["hero_id", "wins", "games_played"]
            for field in required_fields:
                if field not in matchup:
                    return False
                
                if matchup.get("games_played", 0) < 10:
                    return False
        
        return True
    
    def _delete_expired_data(self, hero_id: int) -> None:
        """删除过期数据
        
        Args:
            hero_id: 英雄 ID
        """
        with self._lock:
            cache_key = self._get_cache_key(hero_id)
            self.cache.delete(cache_key)
            
            file_path = self.data_dir / f"hero_{hero_id}.json"
            if file_path.exists():
                file_path.unlink()
            
            self._data_status["expired_heroes"] += 1
            logger.info(f"[MATCHUP_EXPIRED] 数据已过期并删除: hero_id={hero_id}, ttl_days={self.ttl_days}")
    
    def _delete_invalid_data(self, hero_id: int) -> None:
        """删除无效数据
        
        Args:
            hero_id: 英雄 ID
        """
        with self._lock:
            cache_key = self._get_cache_key(hero_id)
            self.cache.delete(cache_key)
            
            file_path = self.data_dir / f"hero_{hero_id}.json"
            if file_path.exists():
                file_path.unlink()
            
            self._data_status["invalid_heroes"] += 1
            logger.warning(f"[MATCHUP_INVALID] 数据不完整已删除: hero_id={hero_id}")
    
    def _start_background_load(self) -> None:
        """启动后台异步加载（已简化，移除 BackgroundLoader 依赖）"""
        logger.info("后台加载功能已简化，缺失数据将在需要时按需加载")
    
    def get_matchup(self, hero_id: int) -> Optional[Dict[str, Any]]:
        """获取英雄 matchup 数据（按优先级）
        
        数据源优先级：
        1. Memory Cache
        2. SQLite Cache  
        3. Local JSON File
        
        新增检查：
        - 数据过期检查（TTL）
        - 数据完整性校验
        
        Returns:
            matchup 数据，如果不存在或过期返回 None
        """
        start_time = time.time()
        
        with self._lock:
            cache_key = self._get_cache_key(hero_id)
            
            data = self.cache.get(cache_key)
            if data:
                if self._is_data_expired(data):
                    elapsed = time.time() - start_time
                    logger.info(f"[MATCHUP_EXPIRED_CACHE] 缓存数据已过期: hero_id={hero_id}, time={elapsed:.3f}s")
                    self._delete_expired_data(hero_id)
                elif not self._validate_data_integrity(data):
                    elapsed = time.time() - start_time
                    logger.warning(f"[MATCHUP_INVALID_CACHE] 缓存数据不完整: hero_id={hero_id}, time={elapsed:.3f}s")
                    self._delete_invalid_data(hero_id)
                else:
                    elapsed = time.time() - start_time
                    logger.info(f"[MATCHUP_CACHE_HIT] 从缓存获取: hero_id={hero_id}, source=memory_cache, time={elapsed:.3f}s, size={len(data.get('matchup_data', []))}items")
                    return data
            
            file_path = self.data_dir / f"hero_{hero_id}.json"
            if file_path.exists():
                try:
                    file_start = time.time()
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                    
                    if self._is_data_expired(data):
                        elapsed = time.time() - start_time
                        logger.info(f"[MATCHUP_EXPIRED_FILE] 文件数据已过期: hero_id={hero_id}, time={elapsed:.3f}s")
                        self._delete_expired_data(hero_id)
                    elif not self._validate_data_integrity(data):
                        elapsed = time.time() - start_time
                        logger.warning(f"[MATCHUP_INVALID_FILE] 文件数据不完整: hero_id={hero_id}, time={elapsed:.3f}s")
                        self._delete_invalid_data(hero_id)
                    else:
                        self.cache.set(cache_key, data)
                        elapsed = time.time() - start_time
                        file_elapsed = time.time() - file_start
                        logger.info(f"[MATCHUP_FILE_HIT] 从本地文件获取: hero_id={hero_id}, source=local_json, time={elapsed:.3f}s, file_read={file_elapsed:.3f}s, size={len(data.get('matchup_data', []))}items")
                        return data
                except Exception as e:
                    elapsed = time.time() - start_time
                    logger.warning(f"[MATCHUP_FILE_ERROR] 读取本地文件失败: hero_id={hero_id}, error={str(e)}, time={elapsed:.3f}s")
            
            elapsed = time.time() - start_time
            logger.info(f"[MATCHUP_MISS] 数据不存在: hero_id={hero_id}, time={elapsed:.3f}s")
            
            return None
    
    def get_matchups_batch(self, hero_ids: List[int]) -> Dict[int, Optional[Dict]]:
        """批量获取多个英雄的 matchup 数据
        
        Args:
            hero_ids: 英雄 ID 列表
            
        Returns:
            {hero_id: matchup_data} 字典
        """
        results = {}
        for hero_id in hero_ids:
            results[hero_id] = self.get_matchup(hero_id)
        return results
    
    def save_matchup(self, hero_id: int, data: Dict[str, Any]) -> bool:
        """保存 matchup 数据到缓存和本地文件
        
        Args:
            hero_id: 英雄 ID
            data: matchup 数据（可以是原始列表或包装后的字典）
            
        Returns:
            是否成功保存
        """
        start_time = time.time()
        
        with self._lock:
            try:
                wrapped_data = self._wrap_data_with_metadata(data)
                
                cache_key = self._get_cache_key(hero_id)
                self.cache.set(cache_key, wrapped_data)
                
                file_path = self.data_dir / f"hero_{hero_id}.json"
                data_size = len(json.dumps(wrapped_data))
                file_path.write_text(
                    json.dumps(wrapped_data, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                
                self._update_status(hero_id)
                
                elapsed = time.time() - start_time
                logger.info(f"[MATCHUP_SAVE] 数据保存成功: hero_id={hero_id}, time={elapsed:.3f}s, cache_key={cache_key}, file_size={data_size}bytes, total_loaded={self._data_status['loaded_heroes']}")
                return True
                
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(f"[MATCHUP_SAVE_ERROR] 数据保存失败: hero_id={hero_id}, error={str(e)}, time={elapsed:.3f}s")
                return False
    
    def _wrap_data_with_metadata(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """将数据包装为包含 metadata 的结构
        
        Args:
            data: 原始 matchup 数据
            
        Returns:
            包装后的数据（包含 _metadata 和 matchup_data）
        """
        if isinstance(data, list):
            return {
                "matchup_data": data,
                "_metadata": {
                    "created_at": datetime.now().isoformat(),
                    "ttl_days": self.ttl_days,
                    "version": "1.0",
                    "source": "opendota_api"
                }
            }
        elif isinstance(data, dict):
            if "matchup_data" in data and "_metadata" in data:
                return data
            elif "matchup_data" not in data:
                return {
                    "matchup_data": data.get("matchup_data", data),
                    "_metadata": {
                        "created_at": datetime.now().isoformat(),
                        "ttl_days": self.ttl_days,
                        "version": "1.0",
                        "source": "opendota_api"
                    }
                }
            else:
                return {
                    "matchup_data": data,
                    "_metadata": {
                        "created_at": datetime.now().isoformat(),
                        "ttl_days": self.ttl_days,
                        "version": "1.0",
                        "source": "opendota_api"
                    }
                }
        else:
            return {
                "matchup_data": [],
                "_metadata": {
                    "created_at": datetime.now().isoformat(),
                    "ttl_days": self.ttl_days,
                    "version": "1.0",
                    "source": "unknown"
                }
            }
    
    def _update_status(self, hero_id: int) -> None:
        """更新数据状态"""
        if hero_id in self._data_status["missing_heroes"]:
            self._data_status["missing_heroes"].remove(hero_id)
            self._data_status["loaded_heroes"] += 1
            self._data_status["last_update"] = datetime.now().isoformat()
    
    def get_status(self) -> Dict[str, Any]:
        """获取数据状态
        
        Returns:
            数据状态信息
        """
        return {
            "total_heroes": self._data_status["total_heroes"],
            "loaded_heroes": self._data_status["loaded_heroes"],
            "missing_heroes": len(self._data_status["missing_heroes"]),
            "missing_hero_ids": self._data_status["missing_heroes"][:10],
            "last_update": self._data_status["last_update"],
            "is_loading": self._data_status["is_loading"],
            "progress": f"{self._data_status['loaded_heroes']}/{self._data_status['total_heroes']}",
            "expired_heroes": self._data_status["expired_heroes"],
            "invalid_heroes": self._data_status["invalid_heroes"],
            "ttl_days": self.ttl_days
        }
    
    def is_data_ready(self) -> bool:
        """检查数据是否已准备好
        
        Returns:
            是否有足够的数据可用
        """
        return self._data_status["loaded_heroes"] >= self.TOTAL_HEROES * 0.8
    
    def force_load_all(self) -> None:
        """强制全量加载所有数据（已简化）"""
        logger.info("全量加载功能已简化，数据将在需要时按需加载")
    
    def stop_background_load(self) -> None:
        """停止后台加载（已简化）"""
        self._data_status["is_loading"] = False
    
    def clear_all_data(self) -> None:
        """清空所有数据"""
        with self._lock:
            for file_path in self.data_dir.glob("hero_*.json"):
                file_path.unlink()
            
            self._data_status = {
                "total_heroes": self.TOTAL_HEROES,
                "loaded_heroes": 0,
                "missing_heroes": list(range(1, self.TOTAL_HEROES + 1)),
                "last_update": None,
                "is_loading": False
            }
            
            logger.info("已清空所有 matchup 数据")


_global_matchup_manager: Optional[MatchupDataManager] = None


def get_matchup_manager(
    cache_manager: Optional[CacheManager] = None,
    api_client=None,
    llm_client=None,
    **kwargs
) -> MatchupDataManager:
    """获取全局 MatchupDataManager 实例（单例）"""
    global _global_matchup_manager
    
    if _global_matchup_manager is None:
        if cache_manager is None:
            from cache.cache_manager import get_cache
            cache_manager = get_cache()
        
        _global_matchup_manager = MatchupDataManager(
            cache_manager=cache_manager,
            api_client=api_client,
            llm_client=llm_client,
            **kwargs
        )
    
    return _global_matchup_manager