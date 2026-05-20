"""Langfuse 配置管理模块

支持从以下来源加载配置（优先级从高到低）：
1. 环境变量
2. YAML 配置文件
3. 默认值

使用方式:
    from utils.langfuse_config import LangfuseConfig
    
    config = LangfuseConfig(config_path="config/langfuse_config.yaml")
    
    if config.enabled:
        client.init(config={
            "public_key": config.public_key,
            "secret_key": config.secret_key,
            "host": config.host
        })
"""

import os
import yaml
from pathlib import Path
from typing import Optional, Dict, Any


class LangfuseConfig:
    """Langfuse 配置管理
    
    Attributes:
        enabled: 是否启用 Langfuse
        host: Langfuse 服务器地址
        public_key: Langfuse 公钥
        secret_key: Langfuse 密钥
        sample_rate: 采样率 (0.0 - 1.0)
    """
    
    DEFAULT_CONFIG: Dict[str, Any] = {
        "enabled": True,
        "host": "http://localhost:3000",
        "public_key": None,
        "secret_key": None,
        "trace": {
            "llm_calls": True,
            "agent_flow": True,
            "tool_calls": True,
            "api_calls": True
        },
        "sample_rate": 1.0
    }
    
    def __init__(self, config_path: Optional[str] = None) -> None:
        """初始化配置管理器
        
        Args:
            config_path: 配置文件路径，可选
        """
        self.config: Dict[str, Any] = self._deep_copy_dict(self.DEFAULT_CONFIG)
        
        if config_path:
            self._load_from_file(config_path)
        
        self._load_from_env()
    
    def _deep_copy_dict(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """深拷贝字典
        
        Args:
            d: 要拷贝的字典
        
        Returns:
            Dict[str, Any]: 拷贝后的字典
        """
        result = {}
        for key, value in d.items():
            if isinstance(value, dict):
                result[key] = self._deep_copy_dict(value)
            else:
                result[key] = value
        return result
    
    def _load_from_file(self, config_path: str) -> None:
        """从 YAML 文件加载配置
        
        Args:
            config_path: 配置文件路径
        """
        path = Path(config_path)
        if not path.exists():
            return
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                yaml_config = yaml.safe_load(f)
                if yaml_config and 'langfuse' in yaml_config:
                    self._merge_config(yaml_config['langfuse'])
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"加载 Langfuse 配置文件失败: {e}")
    
    def _load_from_env(self) -> None:
        """从环境变量加载配置"""
        if os.getenv('LANGFUSE_ENABLED') is not None:
            self.config['enabled'] = os.getenv('LANGFUSE_ENABLED', 'true').lower() == 'true'
        
        if os.getenv('LANGFUSE_HOST'):
            self.config['host'] = os.getenv('LANGFUSE_HOST')
        
        if os.getenv('LANGFUSE_PUBLIC_KEY'):
            self.config['public_key'] = os.getenv('LANGFUSE_PUBLIC_KEY')
        
        if os.getenv('LANGFUSE_SECRET_KEY'):
            self.config['secret_key'] = os.getenv('LANGFUSE_SECRET_KEY')
        
        if os.getenv('LANGFUSE_SAMPLE_RATE'):
            try:
                self.config['sample_rate'] = float(os.getenv('LANGFUSE_SAMPLE_RATE', '1.0'))
            except ValueError:
                pass
    
    def _merge_config(self, override: Dict[str, Any]) -> None:
        """合并配置
        
        Args:
            override: 要合并的配置字典
        """
        for key, value in override.items():
            if isinstance(value, dict) and key in self.config and isinstance(self.config[key], dict):
                self.config[key].update(value)
            else:
                self.config[key] = value
    
    @property
    def enabled(self) -> bool:
        """获取启用状态
        
        Returns:
            bool: 是否启用
        """
        return self.config.get('enabled', True)
    
    @property
    def host(self) -> str:
        """获取主机地址
        
        Returns:
            str: Langfuse 服务器地址
        """
        return self.config.get('host', 'http://localhost:3000')
    
    @property
    def public_key(self) -> Optional[str]:
        """获取公钥
        
        Returns:
            Optional[str]: 公钥，可能为 None
        """
        return self.config.get('public_key')
    
    @property
    def secret_key(self) -> Optional[str]:
        """获取密钥
        
        Returns:
            Optional[str]: 密钥，可能为 None
        """
        return self.config.get('secret_key')
    
    @property
    def sample_rate(self) -> float:
        """获取采样率
        
        Returns:
            float: 采样率 (0.0 - 1.0)
        """
        return self.config.get('sample_rate', 1.0)
    
    @property
    def trace_llm_calls(self) -> bool:
        """是否追踪 LLM 调用
        
        Returns:
            bool: 是否追踪
        """
        trace_config = self.config.get('trace', {})
        return trace_config.get('llm_calls', True)
    
    @property
    def trace_agent_flow(self) -> bool:
        """是否追踪 Agent 流程
        
        Returns:
            bool: 是否追踪
        """
        trace_config = self.config.get('trace', {})
        return trace_config.get('agent_flow', True)
    
    @property
    def trace_tool_calls(self) -> bool:
        """是否追踪工具调用
        
        Returns:
            bool: 是否追踪
        """
        trace_config = self.config.get('trace', {})
        return trace_config.get('tool_calls', True)
    
    @property
    def trace_api_calls(self) -> bool:
        """是否追踪外部 API
        
        Returns:
            bool: 是否追踪
        """
        trace_config = self.config.get('trace', {})
        return trace_config.get('api_calls', True)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典
        
        Returns:
            Dict[str, Any]: 配置字典
        """
        return self._deep_copy_dict(self.config)
