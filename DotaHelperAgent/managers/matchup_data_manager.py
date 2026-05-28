"""英雄 Matchup 数据管理器

统一管理英雄克制数据的多数据源访问，实现优先级访问策略：
1. Memory Cache（最快）
2. SQLite Cache（持久化）
3. Local JSON File（本地存储）
4. LLM Knowledge（兜底）
5. OpenDota API（后台异步更新）
"""

import json
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime

try:
    from ..cache.cache_manager import CacheManager
    from ..utils.log_config import get_logger
    from ..utils.background_loader import BackgroundLoader
except ImportError:
    from cache.cache_manager import CacheManager
    from utils.log_config import get_logger
    from utils.background_loader import BackgroundLoader

logger = get_logger("matchup_data_manager", component="managers")


class MatchupDataManager:
    """英雄 Matchup 数据管理器
    
    特性：
    - 多数据源优先级访问
    - 启动时自动检查数据完整性
    - 后台异步加载缺失数据
    - 本地 JSON 持久化存储
    - 线程安全
    """
    
    TOTAL_HEROES = 124
    
    def __init__(
        self,
        cache_manager: CacheManager,
        api_client,
        llm_client=None,
        data_dir: str = "data/matchups",
        auto_load_on_startup: bool = True
    ):
        """初始化 Matchup 数据管理器
        
        Args:
            cache_manager: 缓存管理器实例
            api_client: OpenDota API 客户端
            llm_client: LLM 客户端（可选，用于 fallback）
            data_dir: 本地 JSON 存储目录
            auto_load_on_startup: 启动时是否自动加载已有数据到缓存
        """
        self.cache = cache_manager
        self.api_client = api_client
        self.llm_client = llm_client
        
        self.data_dir = Path(data_dir)
        if not self.data_dir.is_absolute():
            self.data_dir = Path(__file__).parent.parent / data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self._lock = threading.RLock()
        self._background_loader: Optional[BackgroundLoader] = None
        self._data_status = {
            "total_heroes": self.TOTAL_HEROES,
            "loaded_heroes": 0,
            "missing_heroes": [],
            "last_update": None,
            "is_loading": False
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
        """加载本地 JSON 文件到缓存"""
        logger.info(f"加载 {len(files)} 个本地 matchup 文件到缓存...")
        
        for file_path in files:
            try:
                hero_id = int(file_path.stem.replace("hero_", ""))
                data = json.loads(file_path.read_text(encoding="utf-8"))
                
                cache_key = self._get_cache_key(hero_id)
                self.cache.set(cache_key, data)
                
            except Exception as e:
                logger.warning(f"加载文件 {file_path} 失败: {e}")
        
        logger.info("本地数据加载完成")
    
    def _get_cache_key(self, hero_id: int) -> str:
        """生成缓存键"""
        return f"matchup_hero_{hero_id}"
    
    def _start_background_load(self) -> None:
        """启动后台异步加载"""
        if self._background_loader is None:
            self._background_loader = BackgroundLoader(
                matchup_manager=self,
                api_client=self.api_client,
                rate_limit=1.0  # 1 次/秒，避免 429
            )
        
        missing_ids = self._data_status["missing_heroes"]
        if missing_ids:
            self._data_status["is_loading"] = True
            self._background_loader.start()
            
            for hero_id in missing_ids:
                self._background_loader.add_task(hero_id)
            
            logger.info(f"后台加载已启动，待加载: {len(missing_ids)} 个英雄")
    
    def get_matchup(self, hero_id: int) -> Optional[Dict[str, Any]]:
        """获取英雄 matchup 数据（按优先级）
        
        数据源优先级：
        1. Memory Cache
        2. SQLite Cache  
        3. Local JSON File
        
        Returns:
            matchup 数据，如果不存在返回 None
        """
        start_time = time.time()
        
        with self._lock:
            cache_key = self._get_cache_key(hero_id)
            
            data = self.cache.get(cache_key)
            if data:
                elapsed = time.time() - start_time
                logger.info(f"[MATCHUP_CACHE_HIT] 从缓存获取: hero_id={hero_id}, source=memory_cache, time={elapsed:.3f}s, size={len(data)}items")
                return data
            
            file_path = self.data_dir / f"hero_{hero_id}.json"
            if file_path.exists():
                try:
                    file_start = time.time()
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                    self.cache.set(cache_key, data)
                    elapsed = time.time() - start_time
                    file_elapsed = time.time() - file_start
                    logger.info(f"[MATCHUP_FILE_HIT] 从本地文件获取: hero_id={hero_id}, source=local_json, time={elapsed:.3f}s, file_read={file_elapsed:.3f}s, size={len(data)}items")
                    return data
                except Exception as e:
                    elapsed = time.time() - start_time
                    logger.warning(f"[MATCHUP_FILE_ERROR] 读取本地文件失败: hero_id={hero_id}, error={str(e)}, time={elapsed:.3f}s")
            
            elapsed = time.time() - start_time
            logger.info(f"[MATCHUP_MISS] 数据不存在: hero_id={hero_id}, time={elapsed:.3f}s, 触发后台加载")
            
            if self._background_loader:
                self._background_loader.add_task(hero_id, priority=1)
            
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
            data: matchup 数据
            
        Returns:
            是否成功保存
        """
        start_time = time.time()
        
        with self._lock:
            try:
                cache_key = self._get_cache_key(hero_id)
                self.cache.set(cache_key, data)
                
                file_path = self.data_dir / f"hero_{hero_id}.json"
                data_size = len(json.dumps(data))
                file_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
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
            "progress": f"{self._data_status['loaded_heroes']}/{self._data_status['total_heroes']}"
        }
    
    def is_data_ready(self) -> bool:
        """检查数据是否已准备好
        
        Returns:
            是否有足够的数据可用
        """
        return self._data_status["loaded_heroes"] >= self.TOTAL_HEROES * 0.8
    
    def force_load_all(self) -> None:
        """强制全量加载所有数据"""
        all_hero_ids = list(range(1, self.TOTAL_HEROES + 1))
        missing_ids = [id for id in all_hero_ids if id in self._data_status["missing_heroes"]]
        
        if missing_ids:
            self._start_background_load()
            for hero_id in missing_ids:
                self._background_loader.add_task(hero_id, priority=0)
    
    def stop_background_load(self) -> None:
        """停止后台加载"""
        if self._background_loader:
            self._background_loader.stop()
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