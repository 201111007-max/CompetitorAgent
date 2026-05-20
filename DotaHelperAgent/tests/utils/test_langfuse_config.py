"""Langfuse 配置管理单元测试"""

import os
import pytest
import tempfile
from pathlib import Path


class TestLangfuseConfig:
    """测试 Langfuse 配置管理"""
    
    def test_default_config(self):
        from utils.langfuse_config import LangfuseConfig
        
        config = LangfuseConfig()
        
        assert config.enabled is True
        assert config.host == "http://localhost:3000"
    
    def test_load_from_yaml_file(self):
        from utils.langfuse_config import LangfuseConfig
        
        yaml_content = """
langfuse:
  enabled: false
  host: "http://custom-host:3000"
  public_key: "test_public"
  secret_key: "test_secret"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name
        
        try:
            config = LangfuseConfig(config_path=temp_path)
            
            assert config.enabled is False
            assert config.host == "http://custom-host:3000"
            assert config.public_key == "test_public"
            assert config.secret_key == "test_secret"
        finally:
            os.unlink(temp_path)
    
    def test_load_from_env_variables(self, monkeypatch):
        from utils.langfuse_config import LangfuseConfig
        
        monkeypatch.setenv('LANGFUSE_ENABLED', 'false')
        monkeypatch.setenv('LANGFUSE_HOST', 'http://env-host:3000')
        monkeypatch.setenv('LANGFUSE_PUBLIC_KEY', 'env_public')
        monkeypatch.setenv('LANGFUSE_SECRET_KEY', 'env_secret')
        
        config = LangfuseConfig()
        
        assert config.enabled is False
        assert config.host == "http://env-host:3000"
        assert config.public_key == "env_public"
        assert config.secret_key == "env_secret"
    
    def test_env_overrides_yaml(self, monkeypatch):
        from utils.langfuse_config import LangfuseConfig
        
        yaml_content = """
langfuse:
  enabled: true
  host: "http://yaml-host:3000"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name
        
        try:
            monkeypatch.setenv('LANGFUSE_ENABLED', 'false')
            monkeypatch.setenv('LANGFUSE_HOST', 'http://env-host:3000')
            
            config = LangfuseConfig(config_path=temp_path)
            
            assert config.enabled is False
            assert config.host == "http://env-host:3000"
        finally:
            os.unlink(temp_path)
    
    def test_trace_config_defaults(self):
        from utils.langfuse_config import LangfuseConfig
        
        config = LangfuseConfig()
        
        assert config.trace_llm_calls is True
        assert config.trace_agent_flow is True
        assert config.trace_tool_calls is True
        assert config.trace_api_calls is True
        assert config.sample_rate == 1.0
