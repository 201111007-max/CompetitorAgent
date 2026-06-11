"""并行执行配置管理器"""

from typing import Dict, Any
from pathlib import Path
import yaml
from utils.log_config import get_logger

logger = get_logger("parallel_execution_config", component="core")


class ParallelExecutionConfig:
    """并行执行配置管理器

    负责加载和管理并行执行相关的配置参数
    """

    def __init__(self, config_path: str = "config/parallel_execution_config.yaml"):
        """初始化配置管理器

        Args:
            config_path: 配置文件路径（默认: config/parallel_execution_config.yaml）
        """
        self.config_path = config_path
        self.config = self._load_config(config_path)

        logger.info_ctx(
            "并行执行配置已加载",
            extra_data={
                "config_path": config_path,
                "enabled": self.config.get('enabled', True),
                "max_concurrency": self.config.get('max_concurrency', 5),
                "timeout": self.config.get('timeout', 30)
            }
        )

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """加载配置文件

        Args:
            config_path: 配置文件路径

        Returns:
            配置字典
        """
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
                return config_data.get('parallel_execution', self._default_config())
        except FileNotFoundError:
            logger.warning_ctx(
                f"配置文件不存在: {config_path}, 使用默认配置",
                extra_data={"config_path": config_path}
            )
            return self._default_config()
        except Exception as e:
            logger.error_ctx(
                f"加载配置文件失败: {e}, 使用默认配置",
                extra_data={"config_path": config_path, "error": str(e)}
            )
            return self._default_config()

    def _default_config(self) -> Dict[str, Any]:
        """默认配置

        Returns:
            默认配置字典
        """
        return {
            "enabled": True,
            "max_concurrency": 5,
            "timeout": 30,
            "dependency_analysis": {
                "enabled": True,
                "fallback_to_sequential": True
            },
            "async_execution": {
                "enabled": True,
                "fallback_to_sync": True
            },
            "performance_monitoring": {
                "enabled": True,
                "log_execution_time": True,
                "log_parallel_groups": True
            }
        }

    def get_max_concurrency(self) -> int:
        """获取最大并发数"""
        return self.config.get('max_concurrency', 5)

    def get_timeout(self) -> float:
        """获取超时时间（秒）"""
        return self.config.get('timeout', 30)

    def is_enabled(self) -> bool:
        """是否启用并行执行"""
        return self.config.get('enabled', True)

    def is_dependency_analysis_enabled(self) -> bool:
        """是否启用依赖分析"""
        dependency_config = self.config.get('dependency_analysis', {})
        return dependency_config.get('enabled', True)

    def is_async_execution_enabled(self) -> bool:
        """是否启用异步执行"""
        async_config = self.config.get('async_execution', {})
        return async_config.get('enabled', True)

    def should_fallback_to_sequential(self) -> bool:
        """依赖分析失败时是否降级到顺序执行"""
        dependency_config = self.config.get('dependency_analysis', {})
        return dependency_config.get('fallback_to_sequential', True)

    def should_fallback_to_sync(self) -> bool:
        """异步执行失败时是否降级到同步执行"""
        async_config = self.config.get('async_execution', {})
        return async_config.get('fallback_to_sync', True)

    def is_performance_monitoring_enabled(self) -> bool:
        """是否启用性能监控"""
        monitoring_config = self.config.get('performance_monitoring', {})
        return monitoring_config.get('enabled', True)

    def should_log_execution_time(self) -> bool:
        """是否记录执行时间"""
        monitoring_config = self.config.get('performance_monitoring', {})
        return monitoring_config.get('log_execution_time', True)

    def should_log_parallel_groups(self) -> bool:
        """是否记录并行分组"""
        monitoring_config = self.config.get('performance_monitoring', {})
        return monitoring_config.get('log_parallel_groups', True)
