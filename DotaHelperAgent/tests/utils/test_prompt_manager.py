"""测试 Prompt 管理器模块"""

import pytest
from pathlib import Path
import tempfile
import yaml
import time

from utils.prompt_manager import PromptManager
from utils.prompt_strategy import (
    PromptTemplate,
    LocalYAMLPromptStrategy,
    LangfusePromptStrategy
)


class TestPromptManager:
    """测试 PromptManager"""
    
    def test_init_with_local_strategy(self):
        """测试使用本地策略初始化"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建测试 YAML 文件
            yaml_content = {
                "prompts": {
                    "test_prompt": {
                        "description": "测试 Prompt",
                        "version": 1,
                        "content": "这是测试内容",
                        "variables": [],
                        "metadata": {}
                    }
                }
            }
            
            yaml_file = Path(tmpdir) / "test.yaml"
            with open(yaml_file, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_content, f, allow_unicode=True)
            
            fallback_strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            manager = PromptManager(fallback_strategy=fallback_strategy)
            
            assert manager._fallback == fallback_strategy
            assert manager._cache_ttl == 300
    
    def test_get_prompt_without_variables(self):
        """测试获取不带变量的 Prompt"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_content = {
                "prompts": {
                    "test_prompt": {
                        "description": "测试 Prompt",
                        "version": 1,
                        "content": "这是一个固定的 Prompt",
                        "variables": [],
                        "metadata": {}
                    }
                }
            }
            
            yaml_file = Path(tmpdir) / "test.yaml"
            with open(yaml_file, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_content, f, allow_unicode=True)
            
            fallback_strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            manager = PromptManager(fallback_strategy=fallback_strategy)
            
            content = manager.get_prompt("test_prompt")
            assert content == "这是一个固定的 Prompt"
    
    def test_get_prompt_with_variables(self):
        """测试获取带变量的 Prompt"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_content = {
                "prompts": {
                    "test_prompt": {
                        "description": "测试 Prompt",
                        "version": 1,
                        "content": "你好，{{name}}！你的分数是 {{score}}。",
                        "variables": ["name", "score"],
                        "metadata": {}
                    }
                }
            }
            
            yaml_file = Path(tmpdir) / "test.yaml"
            with open(yaml_file, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_content, f, allow_unicode=True)
            
            fallback_strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            manager = PromptManager(fallback_strategy=fallback_strategy)
            
            content = manager.get_prompt(
                "test_prompt",
                variables={"name": "张三", "score": 95}
            )
            assert content == "你好，张三！你的分数是 95。"
    
    def test_get_prompt_with_version(self):
        """测试获取指定版本的 Prompt"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建版本 1
            yaml_content_v1 = {
                "prompts": {
                    "test_prompt": {
                        "description": "测试 Prompt v1",
                        "version": 1,
                        "content": "版本 1 内容",
                        "variables": [],
                        "metadata": {}
                    }
                }
            }
            
            # 创建版本 2
            yaml_content_v2 = {
                "prompts": {
                    "test_prompt": {
                        "description": "测试 Prompt v2",
                        "version": 2,
                        "content": "版本 2 内容",
                        "variables": [],
                        "metadata": {}
                    }
                }
            }
            
            yaml_file1 = Path(tmpdir) / "test_v1.yaml"
            with open(yaml_file1, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_content_v1, f, allow_unicode=True)
            
            yaml_file2 = Path(tmpdir) / "test_v2.yaml"
            with open(yaml_file2, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_content_v2, f, allow_unicode=True)
            
            fallback_strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            manager = PromptManager(fallback_strategy=fallback_strategy)
            
            # 获取版本 1
            content_v1 = manager.get_prompt("test_prompt", version=1)
            assert content_v1 == "版本 1 内容"
            
            # 获取版本 2
            content_v2 = manager.get_prompt("test_prompt", version=2)
            assert content_v2 == "版本 2 内容"
    
    def test_get_prompt_latest_version(self):
        """测试获取最新版本的 Prompt"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_content = {
                "prompts": {
                    "test_prompt": {
                        "description": "测试 Prompt",
                        "version": 5,
                        "content": "最新版本内容",
                        "variables": [],
                        "metadata": {}
                    }
                }
            }
            
            yaml_file = Path(tmpdir) / "test.yaml"
            with open(yaml_file, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_content, f, allow_unicode=True)
            
            fallback_strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            manager = PromptManager(fallback_strategy=fallback_strategy)
            
            # 不指定版本，应该获取最新版本
            content = manager.get_prompt("test_prompt")
            assert content == "最新版本内容"
    
    def test_cache_mechanism(self):
        """测试缓存机制"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_content = {
                "prompts": {
                    "test_prompt": {
                        "description": "测试 Prompt",
                        "version": 1,
                        "content": "测试内容",
                        "variables": [],
                        "metadata": {}
                    }
                }
            }
            
            yaml_file = Path(tmpdir) / "test.yaml"
            with open(yaml_file, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_content, f, allow_unicode=True)
            
            fallback_strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            manager = PromptManager(fallback_strategy=fallback_strategy, cache_ttl=1)
            
            # 第一次获取（应该从策略加载）
            content1 = manager.get_prompt("test_prompt")
            assert content1 == "测试内容"
            
            # 检查缓存
            cache_key = "test_prompt:latest"
            assert cache_key in manager._cache
            
            # 第二次获取（应该从缓存读取）
            content2 = manager.get_prompt("test_prompt")
            assert content2 == "测试内容"
            
            # 等待缓存过期
            time.sleep(1.1)
            
            # 第三次获取（缓存已过期，应该重新从策略加载）
            content3 = manager.get_prompt("test_prompt")
            assert content3 == "测试内容"
    
    def test_invalidate_cache(self):
        """测试清除缓存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_content = {
                "prompts": {
                    "test_prompt": {
                        "description": "测试 Prompt",
                        "version": 1,
                        "content": "测试内容",
                        "variables": [],
                        "metadata": {}
                    }
                }
            }
            
            yaml_file = Path(tmpdir) / "test.yaml"
            with open(yaml_file, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_content, f, allow_unicode=True)
            
            fallback_strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            manager = PromptManager(fallback_strategy=fallback_strategy)
            
            # 获取 Prompt（会创建缓存）
            manager.get_prompt("test_prompt")
            assert "test_prompt:latest" in manager._cache
            
            # 清除特定 Prompt 的缓存
            manager.invalidate_cache("test_prompt")
            assert "test_prompt:latest" not in manager._cache
            
            # 重新获取（会重新创建缓存）
            manager.get_prompt("test_prompt")
            assert "test_prompt:latest" in manager._cache
            
            # 清除所有缓存
            manager.invalidate_cache()
            assert len(manager._cache) == 0
    
    def test_list_prompts(self):
        """测试列出所有 Prompt"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_content = {
                "prompts": {
                    "prompt_1": {
                        "description": "Prompt 1",
                        "version": 1,
                        "content": "内容 1",
                        "variables": [],
                        "metadata": {}
                    },
                    "prompt_2": {
                        "description": "Prompt 2",
                        "version": 1,
                        "content": "内容 2",
                        "variables": [],
                        "metadata": {}
                    },
                    "prompt_3": {
                        "description": "Prompt 3",
                        "version": 1,
                        "content": "内容 3",
                        "variables": [],
                        "metadata": {}
                    }
                }
            }
            
            yaml_file = Path(tmpdir) / "test.yaml"
            with open(yaml_file, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_content, f, allow_unicode=True)
            
            fallback_strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            manager = PromptManager(fallback_strategy=fallback_strategy)
            
            prompts = manager.list_prompts()
            assert len(prompts) == 3
            assert "prompt_1" in prompts
            assert "prompt_2" in prompts
            assert "prompt_3" in prompts
    
    def test_get_prompt_metadata(self):
        """测试获取 Prompt 元数据"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_content = {
                "prompts": {
                    "test_prompt": {
                        "description": "测试 Prompt",
                        "version": 2,
                        "content": "测试内容",
                        "variables": ["var1", "var2"],
                        "metadata": {
                            "author": "test_author",
                            "tags": ["test", "demo"]
                        }
                    }
                }
            }
            
            yaml_file = Path(tmpdir) / "test.yaml"
            with open(yaml_file, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_content, f, allow_unicode=True)
            
            fallback_strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            manager = PromptManager(fallback_strategy=fallback_strategy)
            
            metadata = manager.get_prompt_metadata("test_prompt")
            assert metadata["name"] == "test_prompt"
            assert metadata["version"] == 2
            assert metadata["variables"] == ["var1", "var2"]
            assert metadata["metadata"]["author"] == "test_author"
            assert metadata["metadata"]["tags"] == ["test", "demo"]
    
    def test_get_cache_stats(self):
        """测试获取缓存统计信息"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_content = {
                "prompts": {
                    "prompt_1": {
                        "description": "Prompt 1",
                        "version": 1,
                        "content": "内容 1",
                        "variables": [],
                        "metadata": {}
                    },
                    "prompt_2": {
                        "description": "Prompt 2",
                        "version": 1,
                        "content": "内容 2",
                        "variables": [],
                        "metadata": {}
                    }
                }
            }
            
            yaml_file = Path(tmpdir) / "test.yaml"
            with open(yaml_file, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_content, f, allow_unicode=True)
            
            fallback_strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            manager = PromptManager(fallback_strategy=fallback_strategy, cache_ttl=600)
            
            # 初始状态
            stats = manager.get_cache_stats()
            assert stats["cache_size"] == 0
            assert stats["cache_ttl"] == 600
            assert stats["cached_prompts"] == []
            
            # 获取一些 Prompt
            manager.get_prompt("prompt_1")
            manager.get_prompt("prompt_2")
            
            # 检查缓存统计
            stats = manager.get_cache_stats()
            assert stats["cache_size"] == 2
            assert "prompt_1:latest" in stats["cached_prompts"]
            assert "prompt_2:latest" in stats["cached_prompts"]


class TestPromptManagerFallback:
    """测试 PromptManager 降级机制"""
    
    def test_fallback_to_local_strategy(self):
        """测试降级到本地策略"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_content = {
                "prompts": {
                    "test_prompt": {
                        "description": "测试 Prompt",
                        "version": 1,
                        "content": "降级策略内容",
                        "variables": [],
                        "metadata": {}
                    }
                }
            }
            
            yaml_file = Path(tmpdir) / "test.yaml"
            with open(yaml_file, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_content, f, allow_unicode=True)
            
            # 创建一个会失败的主策略
            class FailingPrimaryStrategy:
                def get_prompt(self, name, version=None):
                    raise Exception("主策略失败")
                
                def list_prompts(self):
                    return []
            
            primary_strategy = FailingPrimaryStrategy()
            fallback_strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            
            manager = PromptManager(
                primary_strategy=primary_strategy,
                fallback_strategy=fallback_strategy
            )
            
            # 应该降级到本地策略
            content = manager.get_prompt("test_prompt")
            assert content == "降级策略内容"
    
    def test_primary_strategy_success(self):
        """测试主策略成功"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_content = {
                "prompts": {
                    "test_prompt": {
                        "description": "测试 Prompt",
                        "version": 1,
                        "content": "本地策略内容",
                        "variables": [],
                        "metadata": {}
                    }
                }
            }
            
            yaml_file = Path(tmpdir) / "test.yaml"
            with open(yaml_file, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_content, f, allow_unicode=True)
            
            # 创建一个成功的主策略
            class SuccessfulPrimaryStrategy:
                def get_prompt(self, name, version=None):
                    return PromptTemplate(
                        name=name,
                        content="主策略内容",
                        version=1,
                        variables=[],
                        metadata={}
                    )
                
                def list_prompts(self):
                    return ["test_prompt"]
            
            primary_strategy = SuccessfulPrimaryStrategy()
            fallback_strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            
            manager = PromptManager(
                primary_strategy=primary_strategy,
                fallback_strategy=fallback_strategy
            )
            
            # 应该使用主策略
            content = manager.get_prompt("test_prompt")
            assert content == "主策略内容"
