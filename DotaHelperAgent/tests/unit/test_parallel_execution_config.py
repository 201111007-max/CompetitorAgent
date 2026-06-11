# tests/unit/test_parallel_execution_config.py
import pytest
from pathlib import Path
import tempfile
import yaml
from core.parallel_execution_config import ParallelExecutionConfig


def test_load_config_success():
    """测试成功加载配置文件"""
    config_manager = ParallelExecutionConfig()
    assert config_manager.config is not None
    assert config_manager.config['enabled'] == True
    assert config_manager.config['max_concurrency'] == 5
    assert config_manager.config['timeout'] == 30


def test_load_config_file_not_found():
    """测试配置文件不存在时使用默认配置"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "nonexistent.yaml"
        config_manager = ParallelExecutionConfig(config_path=str(config_path))

        # 应该使用默认配置
        assert config_manager.config['enabled'] == True
        assert config_manager.config['max_concurrency'] == 5
        assert config_manager.config['timeout'] == 30


def test_get_max_concurrency():
    """测试获取最大并发数"""
    config_manager = ParallelExecutionConfig()
    assert config_manager.get_max_concurrency() == 5


def test_get_timeout():
    """测试获取超时时间"""
    config_manager = ParallelExecutionConfig()
    assert config_manager.get_timeout() == 30


def test_is_enabled():
    """测试是否启用并行执行"""
    config_manager = ParallelExecutionConfig()
    assert config_manager.is_enabled() == True


def test_is_dependency_analysis_enabled():
    """测试是否启用依赖分析"""
    config_manager = ParallelExecutionConfig()
    assert config_manager.is_dependency_analysis_enabled() == True


def test_is_async_execution_enabled():
    """测试是否启用异步执行"""
    config_manager = ParallelExecutionConfig()
    assert config_manager.is_async_execution_enabled() == True
