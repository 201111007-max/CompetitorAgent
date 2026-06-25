"""测试 Prompt 存储策略模块"""

import pytest
from pathlib import Path
import tempfile
import yaml

from utils.prompt_strategy import (
    PromptTemplate,
    PromptStrategy,
    LocalYAMLPromptStrategy,
    LangfusePromptStrategy
)


class TestPromptTemplate:
    """测试 PromptTemplate 数据类"""
    
    def test_create_prompt_template(self):
        """测试创建 Prompt 模板"""
        template = PromptTemplate(
            name="test_prompt",
            content="这是一个测试 Prompt",
            version=1,
            variables=["var1", "var2"],
            metadata={"author": "test"}
        )
        
        assert template.name == "test_prompt"
        assert template.content == "这是一个测试 Prompt"
        assert template.version == 1
        assert template.variables == ["var1", "var2"]
        assert template.metadata == {"author": "test"}


class TestLocalYAMLPromptStrategy:
    """测试本地 YAML 策略"""
    
    def test_init_with_empty_directory(self):
        """测试初始化空目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            assert strategy.list_prompts() == []
    
    def test_init_with_nonexistent_directory(self):
        """测试初始化不存在的目录"""
        strategy = LocalYAMLPromptStrategy(prompts_dir="/nonexistent/path")
        assert strategy.list_prompts() == []
    
    def test_load_yaml_files(self):
        """测试加载 YAML 文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建测试 YAML 文件
            yaml_content = {
                "prompts": {
                    "test_prompt_1": {
                        "description": "测试 Prompt 1",
                        "version": 1,
                        "content": "这是测试内容 1",
                        "variables": ["var1"],
                        "metadata": {"author": "test"}
                    },
                    "test_prompt_2": {
                        "description": "测试 Prompt 2",
                        "version": 2,
                        "content": "这是测试内容 2",
                        "variables": ["var2"],
                        "metadata": {"author": "test"}
                    }
                }
            }
            
            yaml_file = Path(tmpdir) / "test.yaml"
            with open(yaml_file, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_content, f, allow_unicode=True)
            
            strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            
            # 验证加载的 Prompt
            prompts = strategy.list_prompts()
            assert len(prompts) == 2
            assert "test_prompt_1" in prompts
            assert "test_prompt_2" in prompts
    
    def test_get_prompt_latest_version(self):
        """测试获取最新版本的 Prompt"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_content = {
                "prompts": {
                    "test_prompt": {
                        "description": "测试 Prompt",
                        "version": 3,
                        "content": "版本 3 内容",
                        "variables": [],
                        "metadata": {}
                    }
                }
            }
            
            yaml_file = Path(tmpdir) / "test.yaml"
            with open(yaml_file, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_content, f, allow_unicode=True)
            
            strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            template = strategy.get_prompt("test_prompt")
            
            assert template is not None
            assert template.version == 3
            assert template.content == "版本 3 内容"
    
    def test_get_prompt_specific_version(self):
        """测试获取特定版本的 Prompt"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建包含多个版本的文件
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
            
            # 写入两个文件
            yaml_file1 = Path(tmpdir) / "test_v1.yaml"
            with open(yaml_file1, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_content_v1, f, allow_unicode=True)
            
            yaml_file2 = Path(tmpdir) / "test_v2.yaml"
            with open(yaml_file2, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_content_v2, f, allow_unicode=True)
            
            strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            
            # 获取版本 1
            template_v1 = strategy.get_prompt("test_prompt", version=1)
            assert template_v1 is not None
            assert template_v1.version == 1
            assert template_v1.content == "版本 1 内容"
            
            # 获取版本 2
            template_v2 = strategy.get_prompt("test_prompt", version=2)
            assert template_v2 is not None
            assert template_v2.version == 2
            assert template_v2.content == "版本 2 内容"
    
    def test_get_nonexistent_prompt(self):
        """测试获取不存在的 Prompt"""
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            template = strategy.get_prompt("nonexistent_prompt")
            assert template is None
    
    def test_create_prompt_not_supported(self):
        """测试本地策略不支持创建 Prompt"""
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            
            with pytest.raises(NotImplementedError) as exc_info:
                strategy.create_prompt("test", "content")
            
            assert "read-only" in str(exc_info.value)


class TestLangfusePromptStrategy:
    """测试 Langfuse 策略"""
    
    def test_init_with_client(self):
        """测试使用客户端初始化"""
        mock_client = object()  # 模拟客户端
        strategy = LangfusePromptStrategy(langfuse_client=mock_client)
        assert strategy.client == mock_client
    
    def test_get_prompt_with_mock(self):
        """测试使用模拟客户端获取 Prompt"""
        # 创建模拟客户端
        class MockPrompt:
            def __init__(self):
                self.prompt = "测试 Prompt 内容"
        
        class MockClient:
            def get_prompt(self, name, version=None):
                return MockPrompt()
        
        mock_client = MockClient()
        strategy = LangfusePromptStrategy(langfuse_client=mock_client)
        
        template = strategy.get_prompt("test_prompt")
        assert template is not None
        assert template.content == "测试 Prompt 内容"
    
    def test_get_prompt_failure(self):
        """测试获取 Prompt 失败"""
        class MockClient:
            def get_prompt(self, name, version=None):
                raise Exception("API 错误")
        
        mock_client = MockClient()
        strategy = LangfusePromptStrategy(langfuse_client=mock_client)
        
        template = strategy.get_prompt("test_prompt")
        assert template is None
    
    def test_list_prompts(self):
        """测试列出 Prompt"""
        mock_client = object()
        strategy = LangfusePromptStrategy(langfuse_client=mock_client)
        
        # Langfuse 策略返回空列表
        prompts = strategy.list_prompts()
        assert prompts == []


class TestPromptStrategyInterface:
    """测试策略接口"""
    
    def test_interface_methods(self):
        """测试接口方法"""
        strategy = PromptStrategy()
        
        # 接口方法应该抛出 NotImplementedError
        with pytest.raises(NotImplementedError):
            strategy.get_prompt("test")
        
        with pytest.raises(NotImplementedError):
            strategy.list_prompts()
        
        with pytest.raises(NotImplementedError):
            strategy.create_prompt("test", "content")
