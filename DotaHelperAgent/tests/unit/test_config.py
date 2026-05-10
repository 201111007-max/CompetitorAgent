"""配置类测试"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import (
    MatchupConfig,
    CacheConfig,
    RateLimitConfig,
    LogConfig,
    AgentConfig
)


class TestMatchupConfig:
    """测试 MatchupConfig"""
    
    def test_default_values(self):
        """测试默认值"""
        config = MatchupConfig()
        
        assert config.min_games_threshold == 100
        assert config.min_winrate_threshold == 0.52
        assert config.score_weight == 100.0
        assert config.synergy_weight == 50.0
    
    def test_custom_values(self):
        """测试自定义值"""
        config = MatchupConfig(
            min_games_threshold=50,
            min_winrate_threshold=0.50,
            score_weight=80.0,
            synergy_weight=40.0
        )
        
        assert config.min_games_threshold == 50
        assert config.min_winrate_threshold == 0.50
        assert config.score_weight == 80.0
        assert config.synergy_weight == 40.0


class TestCacheConfig:
    """测试 CacheConfig"""
    
    def test_default_values(self):
        """测试默认值"""
        config = CacheConfig()
        
        assert config.enabled is True
        assert config.cache_dir == "cache"
        assert config.ttl_hours == 24
        assert config.max_size_mb == 100
        assert config.max_items == 1000
        assert config.enable_memory_cache is True
    
    def test_custom_values(self):
        """测试自定义值"""
        config = CacheConfig(
            enabled=False,
            cache_dir="/tmp/cache",
            ttl_hours=48,
            max_size_mb=200,
            max_items=2000,
            enable_memory_cache=False
        )
        
        assert config.enabled is False
        assert config.cache_dir == "/tmp/cache"
        assert config.ttl_hours == 48
        assert config.max_size_mb == 200
        assert config.max_items == 2000
        assert config.enable_memory_cache is False


class TestRateLimitConfig:
    """测试 RateLimitConfig"""
    
    def test_default_values(self):
        """测试默认值"""
        config = RateLimitConfig()
        
        assert config.delay_seconds == 1.0
        assert config.timeout_seconds == 10
        assert config.max_retries == 3
    
    def test_custom_values(self):
        """测试自定义值"""
        config = RateLimitConfig(
            delay_seconds=0.5,
            timeout_seconds=20,
            max_retries=5
        )
        
        assert config.delay_seconds == 0.5
        assert config.timeout_seconds == 20
        assert config.max_retries == 5


class TestLogConfig:
    """测试 LogConfig"""
    
    def test_default_values(self):
        """测试默认值"""
        config = LogConfig()
        
        assert config.level == "INFO"
        assert config.file is None
        assert "%(asctime)s" in config.format
    
    def test_custom_values(self):
        """测试自定义值"""
        config = LogConfig(
            level="DEBUG",
            file="test.log",
            format="%(levelname)s - %(message)s"
        )
        
        assert config.level == "DEBUG"
        assert config.file == "test.log"
        assert config.format == "%(levelname)s - %(message)s"


class TestAgentConfig:
    """测试 AgentConfig"""
    
    def test_default_values(self):
        """测试默认值"""
        config = AgentConfig()
        
        assert config.api_key is None
        assert isinstance(config.rate_limit, RateLimitConfig)
        assert isinstance(config.cache, CacheConfig)
        assert isinstance(config.matchup, MatchupConfig)
        assert isinstance(config.log, LogConfig)
        assert config.top_n_default == 3
        assert isinstance(config.popular_heroes, list)
    
    def test_custom_values(self):
        """测试自定义值"""
        matchup = MatchupConfig(min_games_threshold=50)
        cache = CacheConfig(ttl_hours=48)
        rate_limit = RateLimitConfig(delay_seconds=0.5)
        log = LogConfig(level="DEBUG")
        
        config = AgentConfig(
            api_key="test_key",
            matchup=matchup,
            cache=cache,
            rate_limit=rate_limit,
            log=log,
            top_n_default=5,
            popular_heroes=[1, 2, 3]
        )
        
        assert config.api_key == "test_key"
        assert config.matchup.min_games_threshold == 50
        assert config.cache.ttl_hours == 48
        assert config.rate_limit.delay_seconds == 0.5
        assert config.log.level == "DEBUG"
        assert config.top_n_default == 5
        assert config.popular_heroes == [1, 2, 3]
    
    def test_to_dict(self):
        """测试转换为字典"""
        config = AgentConfig(
            api_key="test_key",
            top_n_default=5
        )
        
        config_dict = config.to_dict()
        
        assert isinstance(config_dict, dict)
        assert config_dict["api_key"] == "test_key"
        assert config_dict["top_n_default"] == 5
        assert "rate_limit" in config_dict
        assert "cache" in config_dict
        assert "matchup" in config_dict
        assert "log" in config_dict
    
    def test_to_dict_structure(self):
        """测试字典结构"""
        config = AgentConfig()
        config_dict = config.to_dict()
        
        assert "delay_seconds" in config_dict["rate_limit"]
        assert "timeout_seconds" in config_dict["rate_limit"]
        assert "max_retries" in config_dict["rate_limit"]
        
        assert "enabled" in config_dict["cache"]
        assert "cache_dir" in config_dict["cache"]
        assert "ttl_hours" in config_dict["cache"]
        assert "max_size_mb" in config_dict["cache"]
        assert "max_items" in config_dict["cache"]
        
        assert "min_games_threshold" in config_dict["matchup"]
        assert "min_winrate_threshold" in config_dict["matchup"]
        assert "score_weight" in config_dict["matchup"]
        
        assert "level" in config_dict["log"]
        assert "file" in config_dict["log"]


class TestConfigIntegration:
    """配置集成测试"""
    
    def test_full_config_chain(self):
        """测试完整配置链"""
        agent_config = AgentConfig(
            api_key="test_key",
            matchup=MatchupConfig(
                min_games_threshold=80,
                min_winrate_threshold=0.55
            ),
            cache=CacheConfig(
                ttl_hours=36,
                max_size_mb=150
            ),
            rate_limit=RateLimitConfig(
                delay_seconds=0.8,
                timeout_seconds=15
            ),
            log=LogConfig(
                level="WARNING",
                file="agent.log"
            ),
            top_n_default=10
        )
        
        config_dict = agent_config.to_dict()
        
        assert config_dict["api_key"] == "test_key"
        assert config_dict["matchup"]["min_games_threshold"] == 80
        assert config_dict["cache"]["ttl_hours"] == 36
        assert config_dict["rate_limit"]["delay_seconds"] == 0.8
        assert config_dict["log"]["level"] == "WARNING"
        assert config_dict["top_n_default"] == 10
    
    def test_config_immutability(self):
        """测试配置不变性（dataclass 默认是可变的，这里测试基本行为）"""
        config1 = MatchupConfig()
        config2 = MatchupConfig()
        
        assert config1.min_games_threshold == config2.min_games_threshold
        
        config1.min_games_threshold = 50
        
        assert config1.min_games_threshold != config2.min_games_threshold
