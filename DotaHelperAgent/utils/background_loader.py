"""后台异步数据加载器

特性：
- 控制请求频率，避免 API 429 错误
- 支持优先级队列（优先加载用户查询的英雄）
- 加载完成后自动保存到 MatchupDataManager
- 线程安全
- 动态速率调整（根据 API 响应自动调整）
"""

import threading
import time
import queue
from typing import Optional, Callable, Any, Tuple
from datetime import datetime

try:
    from ..utils.log_config import get_logger
except ImportError:
    from utils.log_config import get_logger

logger = get_logger("background_loader", component="utils")


class BackgroundLoader:
    """后台异步数据加载器
    
    用于在后台异步加载英雄 matchup 数据，避免阻塞用户请求
    
    Usage:
        loader = BackgroundLoader(matchup_manager, api_client, rate_limit=1.0)
        loader.start()
        loader.add_task(hero_id=1, priority=0)  # 高优先级
        loader.add_task(hero_id=2, priority=1)  # 低优先级
        loader.stop()
    """
    
    def __init__(
        self,
        matchup_manager,
        api_client,
        rate_limit: float = 1.0,
        max_retries: int = 3,
        on_complete_callback: Optional[Callable[[int, bool], None]] = None
    ):
        """初始化后台加载器
        
        Args:
            matchup_manager: MatchupDataManager 实例
            api_client: OpenDota API 客户端
            rate_limit: 请求频率限制（次/秒），默认 1.0
            max_retries: 最大重试次数，默认 3
            on_complete_callback: 加载完成回调函数 (hero_id, success)
        """
        self.matchup_manager = matchup_manager
        self.api_client = api_client
        self.rate_limit = rate_limit
        self.max_retries = max_retries
        self.on_complete_callback = on_complete_callback
        
        self._priority_queue = queue.PriorityQueue()
        self._loading_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.RLock()
        
        self._stats = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "start_time": None,
            "end_time": None
        }
    
    def start(self) -> None:
        """启动后台加载线程"""
        with self._lock:
            if self._running:
                logger.warning("后台加载线程已在运行")
                return
            
            self._running = True
            self._stats["start_time"] = datetime.now().isoformat()
            
            self._loading_thread = threading.Thread(
                target=self._load_loop,
                name="BackgroundLoader",
                daemon=True
            )
            self._loading_thread.start()
            
            logger.info("后台加载线程已启动")
    
    def stop(self) -> None:
        """停止后台加载线程"""
        with self._lock:
            if not self._running:
                return
            
            self._running = False
            self._stats["end_time"] = datetime.now().isoformat()
            
            self._priority_queue.put((999, None))  # 发送停止信号
            
            if self._loading_thread:
                self._loading_thread.join(timeout=5.0)
            
            logger.info("后台加载线程已停止")
    
    def add_task(self, hero_id: int, priority: int = 1) -> None:
        """添加加载任务
        
        Args:
            hero_id: 英雄 ID
            priority: 优先级（0 最高，数字越大优先级越低）
                     0 = 用户查询的英雄（立即加载）
                     1 = 缺失的英雄（按顺序加载）
        """
        if hero_id is None or hero_id <= 0:
            return
        
        with self._lock:
            self._priority_queue.put((priority, hero_id))
            self._stats["total_tasks"] += 1
        
        logger.debug(f"添加加载任务: hero_id={hero_id}, priority={priority}")
    
    def add_batch_tasks(self, hero_ids: list, priority: int = 1) -> None:
        """批量添加加载任务
        
        Args:
            hero_ids: 英雄 ID 列表
            priority: 优先级
        """
        for hero_id in hero_ids:
            self.add_task(hero_id, priority)
    
    def _load_loop(self) -> None:
        """后台加载循环"""
        logger.info("后台加载循环开始")
        
        while self._running:
            try:
                priority, hero_id = self._priority_queue.get(timeout=1.0)
                
                if hero_id is None:
                    break
                
                self._load_hero_matchup(hero_id)
                
                time.sleep(1.0 / self.rate_limit)
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"后台加载异常: {e}")
        
        logger.info("后台加载循环结束")
    
    def _load_hero_matchup(self, hero_id: int) -> bool:
        """加载单个英雄的 matchup 数据
        
        Args:
            hero_id: 英雄 ID
            
        Returns:
            是否成功加载
        """
        start_time = time.time()
        logger.info(f"[BG_LOAD_START] 开始加载: hero_id={hero_id}, queue_size={self._priority_queue.qsize()}")
        
        for retry in range(self.max_retries):
            retry_start = time.time()
            
            try:
                api_start = time.time()
                matchup_data = self.api_client.get_hero_matchups(hero_id)
                api_elapsed = time.time() - api_start
                
                if matchup_data is not None and len(matchup_data) > 0:
                    save_start = time.time()
                    self.matchup_manager.save_matchup(hero_id, matchup_data)
                    save_elapsed = time.time() - save_start
                    
                    with self._lock:
                        self._stats["completed_tasks"] += 1
                    
                    total_elapsed = time.time() - start_time
                    
                    if self.on_complete_callback:
                        self.on_complete_callback(hero_id, True)
                    
                    logger.info(f"[BG_LOAD_SUCCESS] 加载成功: hero_id={hero_id}, retry={retry}, api_time={api_elapsed:.2f}s, save_time={save_elapsed:.3f}s, total_time={total_elapsed:.2f}s, data_size={len(matchup_data)}items")
                    return True
                else:
                    retry_elapsed = time.time() - retry_start
                    logger.warning(f"[BG_LOAD_EMPTY] 返回空数据: hero_id={hero_id}, retry={retry+1}/{self.max_retries}, api_time={api_elapsed:.2f}s, retry_time={retry_elapsed:.2f}s")
                    
            except Exception as e:
                retry_elapsed = time.time() - retry_start
                logger.warning(f"[BG_LOAD_ERROR] 加载异常: hero_id={hero_id}, error={type(e).__name__}, retry={retry+1}/{self.max_retries}, retry_time={retry_elapsed:.2f}s")
        
        with self._lock:
            self._stats["failed_tasks"] += 1
        
        total_elapsed = time.time() - start_time
        
        if self.on_complete_callback:
            self.on_complete_callback(hero_id, False)
        
        logger.error(f"[BG_LOAD_FAILED] 加载失败: hero_id={hero_id}, retries={self.max_retries}, total_time={total_elapsed:.2f}s")
        return False
    
    def get_stats(self) -> dict:
        """获取加载统计信息"""
        with self._lock:
            queue_size = self._priority_queue.qsize()
            
            return {
                "running": self._running,
                "queue_size": queue_size,
                "total_tasks": self._stats["total_tasks"],
                "completed_tasks": self._stats["completed_tasks"],
                "failed_tasks": self._stats["failed_tasks"],
                "success_rate": (
                    self._stats["completed_tasks"] / self._stats["total_tasks"] * 100
                    if self._stats["total_tasks"] > 0 else 0
                ),
                "start_time": self._stats["start_time"],
                "end_time": self._stats["end_time"]
            }
    
    def is_running(self) -> bool:
        """检查是否正在运行"""
        return self._running
    
    def get_queue_size(self) -> int:
        """获取队列大小"""
        return self._priority_queue.qsize()
    
    def clear_queue(self) -> None:
        """清空队列"""
        while not self._priority_queue.empty():
            try:
                self._priority_queue.get_nowait()
            except queue.Empty:
                break
        
        logger.info("加载队列已清空")


class SmartBackgroundLoader(BackgroundLoader):
    """智能后台加载器
    
    增强功能：
    - 自动检测 API 状态（429 错误时暂停）
    - 动态调整请求频率（根据成功率）
    - 支持暂停/恢复
    - 历史成功率追踪
    """
    
    def __init__(
        self,
        matchup_manager,
        api_client,
        rate_limit: float = 1.0,
        max_retries: int = 3,
        on_complete_callback: Optional[Callable[[int, bool], None]] = None,
        min_rate_limit: float = 0.1,
        max_rate_limit: float = 2.0
    ):
        """初始化智能后台加载器
        
        Args:
            matchup_manager: MatchupDataManager 实例
            api_client: OpenDota API 客户端
            rate_limit: 初始请求频率限制（次/秒），默认 1.0
            max_retries: 最大重试次数，默认 3
            on_complete_callback: 加载完成回调函数 (hero_id, success)
            min_rate_limit: 最小请求频率（次/秒），默认 0.1
            max_rate_limit: 最大请求频率（次/秒），默认 2.0
        """
        super().__init__(
            matchup_manager=matchup_manager,
            api_client=api_client,
            rate_limit=rate_limit,
            max_retries=max_retries,
            on_complete_callback=on_complete_callback
        )
        
        self.min_rate_limit = min_rate_limit
        self.max_rate_limit = max_rate_limit
        
        self._paused = False
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._adaptive_rate_limit = rate_limit
        self._last_429_time: Optional[float] = None
        self._429_count = 0
        
        self._enhanced_stats = {
            "total_429_errors": 0,
            "rate_adjustments": 0,
            "pause_count": 0,
            "resume_count": 0,
            "avg_success_rate": 0.0,
            "current_rate_limit": rate_limit
        }
    
    def pause(self) -> None:
        """暂停加载"""
        self._paused = True
        self._enhanced_stats["pause_count"] += 1
        logger.info("[BG_PAUSE] 后台加载已暂停")
    
    def resume(self) -> None:
        """恢复加载"""
        self._paused = False
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._adaptive_rate_limit = self.rate_limit
        self._enhanced_stats["resume_count"] += 1
        logger.info("[BG_RESUME] 后台加载已恢复")
    
    def _adjust_rate_limit(self, success: bool) -> None:
        """动态调整速率限制
        
        Args:
            success: 本次请求是否成功
        """
        if success:
            self._consecutive_successes += 1
            self._consecutive_failures = 0
            
            if self._consecutive_successes >= 5:
                self._adaptive_rate_limit = min(
                    self.max_rate_limit,
                    self._adaptive_rate_limit * 1.1
                )
                self._enhanced_stats["rate_adjustments"] += 1
                logger.info(
                    f"[BG_RATE_UP] 连续成功 {self._consecutive_successes} 次，"
                    f"提高请求频率至 {self._adaptive_rate_limit:.2f} 次/秒"
                )
        else:
            self._consecutive_failures += 1
            self._consecutive_successes = 0
            
            if self._consecutive_failures >= 2:
                self._adaptive_rate_limit = max(
                    self.min_rate_limit,
                    self._adaptive_rate_limit * 0.8
                )
                self._enhanced_stats["rate_adjustments"] += 1
                logger.warning(
                    f"[BG_RATE_DOWN] 连续失败 {self._consecutive_failures} 次，"
                    f"降低请求频率至 {self._adaptive_rate_limit:.2f} 次/秒"
                )
        
        self._enhanced_stats["current_rate_limit"] = self._adaptive_rate_limit
    
    def _handle_429_error(self) -> None:
        """处理 429 错误"""
        self._429_count += 1
        self._last_429_time = time.time()
        self._enhanced_stats["total_429_errors"] += 1
        
        self._adaptive_rate_limit = max(
            self.min_rate_limit,
            self._adaptive_rate_limit * 0.5
        )
        
        logger.warning(
            f"[BG_429_DETECTED] 检测到 429 错误，"
            f"降低请求频率至 {self._adaptive_rate_limit:.2f} 次/秒，"
            f"暂停 10 秒"
        )
        
        time.sleep(10.0)
    
    def _load_loop(self) -> None:
        """智能后台加载循环"""
        logger.info("[BG_SMART_START] 智能后台加载循环开始")
        
        while self._running:
            if self._paused:
                time.sleep(1.0)
                continue
            
            try:
                priority, hero_id = self._priority_queue.get(timeout=1.0)
                
                if hero_id is None:
                    break
                
                success = self._load_hero_matchup(hero_id)
                
                self._adjust_rate_limit(success)
                
                wait_time = 1.0 / self._adaptive_rate_limit
                logger.debug(
                    f"[BG_WAIT] 等待 {wait_time:.2f}s "
                    f"(rate_limit={self._adaptive_rate_limit:.2f} 次/秒)"
                )
                time.sleep(wait_time)
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[BG_SMART_ERROR] 智能后台加载异常: {e}")
        
        logger.info("[BG_SMART_END] 智能后台加载循环结束")
    
    def _load_hero_matchup(self, hero_id: int) -> bool:
        """加载单个英雄的 matchup 数据（增强版）
        
        Args:
            hero_id: 英雄 ID
            
        Returns:
            是否成功加载
        """
        start_time = time.time()
        logger.info(f"[BG_LOAD_START] 开始加载: hero_id={hero_id}, queue_size={self._priority_queue.qsize()}, rate_limit={self._adaptive_rate_limit:.2f}")
        
        for retry in range(self.max_retries):
            retry_start = time.time()
            
            try:
                api_start = time.time()
                matchup_data = self.api_client.get_hero_matchups(hero_id)
                api_elapsed = time.time() - api_start
                
                if matchup_data is not None and len(matchup_data) > 0:
                    save_start = time.time()
                    self.matchup_manager.save_matchup(hero_id, matchup_data)
                    save_elapsed = time.time() - save_start
                    
                    with self._lock:
                        self._stats["completed_tasks"] += 1
                    
                    total_elapsed = time.time() - start_time
                    
                    if self.on_complete_callback:
                        self.on_complete_callback(hero_id, True)
                    
                    logger.info(f"[BG_LOAD_SUCCESS] 加载成功: hero_id={hero_id}, retry={retry}, api_time={api_elapsed:.2f}s, save_time={save_elapsed:.3f}s, total_time={total_elapsed:.2f}s, data_size={len(matchup_data)}items")
                    return True
                else:
                    retry_elapsed = time.time() - retry_start
                    logger.warning(f"[BG_LOAD_EMPTY] 返回空数据: hero_id={hero_id}, retry={retry+1}/{self.max_retries}, api_time={api_elapsed:.2f}s, retry_time={retry_elapsed:.2f}s")
                    
            except Exception as e:
                retry_elapsed = time.time() - retry_start
                
                if "429" in str(e) or "rate limit" in str(e).lower():
                    self._handle_429_error()
                else:
                    logger.warning(f"[BG_LOAD_ERROR] 加载异常: hero_id={hero_id}, error={type(e).__name__}, retry={retry+1}/{self.max_retries}, retry_time={retry_elapsed:.2f}s")
        
        with self._lock:
            self._stats["failed_tasks"] += 1
        
        total_elapsed = time.time() - start_time
        
        if self.on_complete_callback:
            self.on_complete_callback(hero_id, False)
        
        logger.error(f"[BG_LOAD_FAILED] 加载失败: hero_id={hero_id}, retries={self.max_retries}, total_time={total_elapsed:.2f}s")
        return False
    
    def get_stats(self) -> dict:
        """获取增强统计信息"""
        base_stats = super().get_stats()
        
        total_tasks = self._stats["total_tasks"]
        completed_tasks = self._stats["completed_tasks"]
        
        avg_success_rate = (
            completed_tasks / total_tasks * 100 if total_tasks > 0 else 0
        )
        self._enhanced_stats["avg_success_rate"] = avg_success_rate
        
        base_stats.update({
            "paused": self._paused,
            "consecutive_failures": self._consecutive_failures,
            "consecutive_successes": self._consecutive_successes,
            "adaptive_rate_limit": self._adaptive_rate_limit,
            "min_rate_limit": self.min_rate_limit,
            "max_rate_limit": self.max_rate_limit,
            "total_429_errors": self._enhanced_stats["total_429_errors"],
            "rate_adjustments": self._enhanced_stats["rate_adjustments"],
            "pause_count": self._enhanced_stats["pause_count"],
            "resume_count": self._enhanced_stats["resume_count"],
            "avg_success_rate": avg_success_rate
        })
        return base_stats
    
    def get_rate_limit_history(self) -> dict:
        """获取速率调整历史"""
        return {
            "initial_rate_limit": self.rate_limit,
            "current_rate_limit": self._adaptive_rate_limit,
            "min_rate_limit": self.min_rate_limit,
            "max_rate_limit": self.max_rate_limit,
            "adjustments_count": self._enhanced_stats["rate_adjustments"],
            "429_errors": self._enhanced_stats["total_429_errors"]
        }