"""DotaHelperAgent - Dota 2 英雄推荐助手"""

from .core.agent import DotaHelperAgent
from .utils.api_client import OpenDotaClient
from .analyzers.hero_analyzer import HeroAnalyzer
from .analyzers.item_recommender import ItemRecommender
from .analyzers.skill_builder import SkillBuilder
from .strategies.score_strategies import IScoreStrategy, WinRateStrategy, PopularityStrategy
from .cache.cache_manager import CacheManager, get_cache
from .core.config import (
    AgentConfig,
    MatchupConfig,
    CacheConfig,
    RateLimitConfig,
    LogConfig,
)

__version__ = "1.0.0"
__all__ = [
    # 核心类
    "DotaHelperAgent",
    "OpenDotaClient",
    "HeroAnalyzer",
    "ItemRecommender",
    "SkillBuilder",
    
    # 缓存
    "CacheManager",
    "get_cache",
    
    # 策略
    "IScoreStrategy",
    "WinRateStrategy",
    "PopularityStrategy",
    
    # 配置
    "AgentConfig",
    "MatchupConfig",
    "CacheConfig",
    "RateLimitConfig",
    "LogConfig",
]
