"""配置管理模块"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MatchupConfig:
    """克制分析配置"""
    
    # 最小比赛场次阈值
    min_games_threshold: int = 100
    
    # 最小胜率阈值
    min_winrate_threshold: float = 0.52
    
    # 得分权重
    score_weight: float = 100.0
    
    # 配合分数权重
    synergy_weight: float = 50.0


@dataclass
class CacheConfig:
    """缓存配置"""
    
    # 是否启用缓存
    enabled: bool = True
    
    # 缓存目录
    cache_dir: str = "cache"
    
    # 缓存过期时间（小时）
    ttl_hours: int = 24
    
    # 最大缓存大小（MB）
    max_size_mb: int = 100
    
    # 最大缓存项数量
    max_items: int = 1000
    
    # 是否启用内存缓存
    enable_memory_cache: bool = True


@dataclass
class RateLimitConfig:
    """速率限制配置"""
    
    # 请求间隔（秒）
    delay_seconds: float = 1.0
    
    # 超时时间（秒）
    timeout_seconds: int = 10
    
    # 最大重试次数
    max_retries: int = 3


@dataclass
class LogConfig:
    """日志配置"""
    
    # 日志级别
    level: str = "INFO"
    
    # 日志文件（None 表示输出到控制台）
    file: Optional[str] = None
    
    # 日志格式
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


@dataclass
class AgentConfig:
    """Agent 总配置"""
    
    # API 配置
    api_key: Optional[str] = None
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    
    # 缓存配置
    cache: CacheConfig = field(default_factory=CacheConfig)
    
    # 分析配置
    matchup: MatchupConfig = field(default_factory=MatchupConfig)
    
    # 日志配置
    log: LogConfig = field(default_factory=LogConfig)
    
    # 默认推荐数量
    top_n_default: int = 3
    
    # 热门英雄 ID 列表（用于缓存预热）
    popular_heroes: List[int] = field(default_factory=lambda: [
        1, 2, 5, 10, 15, 20, 25, 30, 35, 40
    ])
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "api_key": self.api_key,
            "rate_limit": {
                "delay_seconds": self.rate_limit.delay_seconds,
                "timeout_seconds": self.rate_limit.timeout_seconds,
                "max_retries": self.rate_limit.max_retries,
            },
            "cache": {
                "enabled": self.cache.enabled,
                "cache_dir": self.cache.cache_dir,
                "ttl_hours": self.cache.ttl_hours,
                "max_size_mb": self.cache.max_size_mb,
                "max_items": self.cache.max_items,
            },
            "matchup": {
                "min_games_threshold": self.matchup.min_games_threshold,
                "min_winrate_threshold": self.matchup.min_winrate_threshold,
                "score_weight": self.matchup.score_weight,
            },
            "log": {
                "level": self.log.level,
                "file": self.log.file,
            },
            "top_n_default": self.top_n_default,
        }
