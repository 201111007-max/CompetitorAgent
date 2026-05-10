"""配置管理模块

支持从 YAML 配置文件加载配置，也支持代码中直接配置
"""

from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path
import yaml


def load_llm_config_from_yaml(config_path: Optional[str] = None) -> dict:
    """从 YAML 配置文件加载 LLM 配置
    
    Args:
        config_path: 配置文件路径，如果为 None 则使用默认路径
        
    Returns:
        配置字典
    """
    if config_path is None:
        # 默认配置文件路径
        default_paths = [
            Path(__file__).parent.parent / "config" / "llm_config.yaml",
            Path(__file__).parent / "config" / "llm_config.yaml",
            Path("config") / "llm_config.yaml",
            Path("llm_config.yaml"),
        ]
        
        for path in default_paths:
            if path.exists():
                config_path = str(path)
                break
    
    if config_path and Path(config_path).exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                return config.get('llm', {})
        except Exception as e:
            print(f"⚠️ 加载 LLM 配置文件失败：{e}")
            print("   将使用默认配置")
    
    return {}


@dataclass
class LLMConfig:
    """LLM 配置
    
    支持从 YAML 配置文件加载，也支持代码中直接配置
    优先级：代码配置 > YAML 配置文件 > 默认值
    """
    
    # 是否启用 LLM
    enabled: bool = True
    
    # API 基础 URL（本地部署）
    base_url: str = "http://127.0.0.1:1234/v1"
    
    # 模型名称
    model: str = "qwen3.5-9b"
    
    # API Key（本地部署通常不需要）
    api_key: Optional[str] = None
    
    # 生成参数
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: float = 0.9
    
    # 超时时间（秒）
    timeout: int = 60
    
    # 是否启用流式输出
    stream: bool = False
    
    @classmethod
    def from_yaml(cls, config_path: Optional[str] = None, **overrides) -> 'LLMConfig':
        """从 YAML 配置文件创建 LLMConfig
        
        Args:
            config_path: 配置文件路径，如果为 None 则使用默认路径
            overrides: 覆盖参数，优先级高于配置文件
            
        Returns:
            LLMConfig 实例
        """
        # 从配置文件加载
        yaml_config = load_llm_config_from_yaml(config_path)
        
        # 合并配置（overrides 优先级最高）
        merged = {**yaml_config, **overrides}
        
        return cls(
            enabled=merged.get('enabled', cls.enabled),
            base_url=merged.get('base_url', cls.base_url),
            model=merged.get('model', cls.model),
            api_key=merged.get('api_key', cls.api_key),
            temperature=merged.get('temperature', cls.temperature),
            max_tokens=merged.get('max_tokens', cls.max_tokens),
            top_p=merged.get('top_p', cls.top_p),
            timeout=merged.get('timeout', cls.timeout),
            stream=merged.get('stream', cls.stream),
        )


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
    
    # LLM 配置
    llm: LLMConfig = field(default_factory=LLMConfig)
    
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
            "llm": {
                "enabled": self.llm.enabled,
                "base_url": self.llm.base_url,
                "model": self.llm.model,
                "temperature": self.llm.temperature,
                "max_tokens": self.llm.max_tokens,
            },
            "top_n_default": self.top_n_default,
        }
