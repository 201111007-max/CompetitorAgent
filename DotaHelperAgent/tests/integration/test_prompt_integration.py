"""Prompt 管理系统集成测试

测试 Prompt 管理系统与实际业务模块的集成
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.prompt_manager import PromptManager, PromptNotFoundError
from utils.prompt_strategy import LocalYAMLPromptStrategy, LangfusePromptStrategy, PromptTemplate


class TestPromptManagerIntegration:
    """测试 PromptManager 与业务模块的集成"""
    
    def test_load_all_yaml_configs(self):
        """测试加载所有本地 YAML 配置文件"""
        config_dir = Path(__file__).parent.parent.parent / "config" / "prompts"
        
        if not config_dir.exists():
            pytest.skip("config/prompts 目录不存在")
        
        strategy = LocalYAMLPromptStrategy(prompts_dir=str(config_dir))
        manager = PromptManager(fallback_strategy=strategy)
        
        # 验证所有 Prompt 都被加载
        prompts = manager.list_prompts()
        
        # 检查关键 Prompt 是否存在
        expected_prompts = [
            "assistant_system",
            "assistant_general_chat",
            "assistant_fallback",
            "assistant_fallback_with_search",
            "hero_recommendation",
            "hero_recommendation_json",
            "item_recommendation",
            "hero_explanation",
            "team_analysis",
            "game_advice",
            "skill_build"
        ]
        
        for prompt_name in expected_prompts:
            assert prompt_name in prompts, f"Prompt '{prompt_name}' 未被加载"
    
    def test_variable_substitution_in_real_prompts(self):
        """测试真实 Prompt 中的变量替换"""
        config_dir = Path(__file__).parent.parent.parent / "config" / "prompts"
        
        if not config_dir.exists():
            pytest.skip("config/prompts 目录不存在")
        
        strategy = LocalYAMLPromptStrategy(prompts_dir=str(config_dir))
        manager = PromptManager(fallback_strategy=strategy)
        
        # 测试 assistant_general_chat 的变量替换
        content = manager.get_prompt(
            "assistant_general_chat",
            variables={"query": "如何克制帕吉？"}
        )
        assert "如何克制帕吉？" in content
        assert "{{query}}" not in content
        
        # 测试 hero_recommendation_json 的变量替换
        content = manager.get_prompt(
            "hero_recommendation_json",
            variables={
                "top_n": "3",
                "our_team": "斧王,影魔",
                "enemy_team": "帕吉,宙斯"
            }
        )
        assert "3" in content
        assert "斧王,影魔" in content
        assert "帕吉,宙斯" in content
        assert "{{top_n}}" not in content
        assert "{{our_team}}" not in content
        assert "{{enemy_team}}" not in content
        
        # 测试 game_advice 的变量替换（多个变量）
        content = manager.get_prompt(
            "game_advice",
            variables={
                "hero_name": "影魔",
                "health": "1200",
                "max_health": "2000",
                "health_percent": "60.0",
                "mana": "800",
                "max_mana": "1000",
                "mana_percent": "80.0",
                "gold": "5000",
                "game_time_formatted": "25分30秒",
                "kills": "10",
                "deaths": "3",
                "assists": "15",
                "event_type": "低血量警告",
                "knowledge_text": "建议回城补给"
            }
        )
        assert "影魔" in content
        assert "1200" in content
        assert "60.0%" in content
        assert "25分30秒" in content
        assert "低血量警告" in content
        assert "建议回城补给" in content
    
    def test_prompt_metadata_retrieval(self):
        """测试获取 Prompt 元数据"""
        config_dir = Path(__file__).parent.parent.parent / "config" / "prompts"
        
        if not config_dir.exists():
            pytest.skip("config/prompts 目录不存在")
        
        strategy = LocalYAMLPromptStrategy(prompts_dir=str(config_dir))
        manager = PromptManager(fallback_strategy=strategy)
        
        # 测试获取 assistant_system 的元数据
        metadata = manager.get_prompt_metadata("assistant_system")
        
        assert metadata["name"] == "assistant_system"
        assert metadata["version"] == 1
        assert metadata["variables"] == []
        assert "author" in metadata["metadata"]
        assert "tags" in metadata["metadata"]
        assert "system" in metadata["metadata"]["tags"]
    
    def test_cache_integration(self):
        """测试缓存机制在集成场景中的工作"""
        config_dir = Path(__file__).parent.parent.parent / "config" / "prompts"
        
        if not config_dir.exists():
            pytest.skip("config/prompts 目录不存在")
        
        strategy = LocalYAMLPromptStrategy(prompts_dir=str(config_dir))
        manager = PromptManager(fallback_strategy=strategy, cache_ttl=60)
        
        # 第一次获取（应该从文件加载）
        content1 = manager.get_prompt("assistant_system")
        
        # 检查缓存状态
        stats = manager.get_cache_stats()
        assert stats["cache_size"] > 0
        assert "assistant_system:latest" in stats["cached_prompts"]
        
        # 第二次获取（应该从缓存读取）
        content2 = manager.get_prompt("assistant_system")
        assert content1 == content2
        
        # 清除缓存
        manager.invalidate_cache("assistant_system")
        stats = manager.get_cache_stats()
        assert "assistant_system:latest" not in stats["cached_prompts"]
    
    def test_fallback_mechanism(self):
        """测试降级机制"""
        config_dir = Path(__file__).parent.parent.parent / "config" / "prompts"
        
        if not config_dir.exists():
            pytest.skip("config/prompts 目录不存在")
        
        # 创建一个会失败的主策略
        failing_strategy = Mock()
        failing_strategy.get_prompt.side_effect = Exception("主策略失败")
        failing_strategy.list_prompts.return_value = []
        
        # 使用本地策略作为降级
        fallback_strategy = LocalYAMLPromptStrategy(prompts_dir=str(config_dir))
        
        manager = PromptManager(
            primary_strategy=failing_strategy,
            fallback_strategy=fallback_strategy
        )
        
        # 应该降级到本地策略
        content = manager.get_prompt("assistant_system")
        assert content is not None
        assert "Dota 2" in content
    
    def test_prompt_not_found_error(self):
        """测试 Prompt 未找到时的错误处理"""
        config_dir = Path(__file__).parent.parent.parent / "config" / "prompts"
        
        if not config_dir.exists():
            pytest.skip("config/prompts 目录不存在")
        
        strategy = LocalYAMLPromptStrategy(prompts_dir=str(config_dir))
        manager = PromptManager(fallback_strategy=strategy)
        
        # 尝试获取不存在的 Prompt
        with pytest.raises(PromptNotFoundError):
            manager.get_prompt("nonexistent_prompt")


class TestBusinessModuleIntegration:
    """测试业务模块与 PromptManager 的集成"""
    
    def test_agent_controller_integration(self):
        """测试 AgentController 与 PromptManager 的集成"""
        from core.agent_controller import AgentController
        from core.tool_registry import ToolRegistry
        
        config_dir = Path(__file__).parent.parent.parent / "config" / "prompts"
        
        if not config_dir.exists():
            pytest.skip("config/prompts 目录不存在")
        
        strategy = LocalYAMLPromptStrategy(prompts_dir=str(config_dir))
        prompt_manager = PromptManager(fallback_strategy=strategy)
        
        # 创建模拟的 LLM 客户端
        mock_llm_client = Mock()
        mock_llm_client.chat.return_value = {
            "choices": [{"message": {"content": "测试回答"}}]
        }
        
        # 创建 AgentController（传入 prompt_manager）
        tool_registry = ToolRegistry()
        controller = AgentController(
            tool_registry=tool_registry,
            llm_client=mock_llm_client,
            prompt_manager=prompt_manager
        )
        
        # 验证 prompt_manager 被正确设置
        assert controller.prompt_manager is not None
        assert controller.prompt_manager == prompt_manager
    
    def test_llm_analyzer_integration(self):
        """测试 DotaLLMAnalyzer 与 PromptManager 的集成"""
        from utils.llm_client import DotaLLMAnalyzer, LLMClient
        
        config_dir = Path(__file__).parent.parent.parent / "config" / "prompts"
        
        if not config_dir.exists():
            pytest.skip("config/prompts 目录不存在")
        
        strategy = LocalYAMLPromptStrategy(prompts_dir=str(config_dir))
        prompt_manager = PromptManager(fallback_strategy=strategy)
        
        # 创建模拟的 LLM 客户端
        mock_llm_client = Mock(spec=LLMClient)
        mock_llm_client.complete.return_value = "测试解释"
        
        # 创建 DotaLLMAnalyzer（传入 prompt_manager）
        analyzer = DotaLLMAnalyzer(mock_llm_client, prompt_manager=prompt_manager)
        
        # 验证 prompt_manager 被正确设置
        assert analyzer.prompt_manager is not None
        assert analyzer.prompt_manager == prompt_manager
        
        # 测试调用方法（验证 Prompt 被正确获取和渲染）
        result = analyzer.explain_recommendation(
            hero_name="影魔",
            enemy_heroes=["帕吉", "宙斯"],
            win_rate=0.65,
            reasons=["高爆发", "克制脆皮"]
        )
        
        # 验证 LLM 被调用
        assert mock_llm_client.complete.called
        
        # 获取传递给 LLM 的 Prompt
        call_args = mock_llm_client.complete.call_args
        prompt = call_args[0][0]
        
        # 验证变量被正确替换
        assert "影魔" in prompt
        assert "帕吉,宙斯" in prompt or "帕吉" in prompt
        assert "65.0%" in prompt
    
    def test_llm_engine_integration(self):
        """测试 LLMEngine 与 PromptManager 的集成"""
        from core.decision.llm_engine import LLMEngine
        
        config_dir = Path(__file__).parent.parent.parent / "config" / "prompts"
        
        if not config_dir.exists():
            pytest.skip("config/prompts 目录不存在")
        
        strategy = LocalYAMLPromptStrategy(prompts_dir=str(config_dir))
        prompt_manager = PromptManager(fallback_strategy=strategy)
        
        # 创建 LLMEngine（传入 prompt_manager）
        engine = LLMEngine(prompt_manager=prompt_manager)
        
        # 验证 prompt_manager 被正确设置
        assert engine.prompt_manager is not None
        assert engine.prompt_manager == prompt_manager
    
    def test_skill_builder_integration(self):
        """测试 HybridSkillBuilder 与 PromptManager 的集成"""
        from analyzers.skill_builder import HybridSkillBuilder
        from utils.api_client import OpenDotaClient
        
        config_dir = Path(__file__).parent.parent.parent / "config" / "prompts"
        
        if not config_dir.exists():
            pytest.skip("config/prompts 目录不存在")
        
        strategy = LocalYAMLPromptStrategy(prompts_dir=str(config_dir))
        prompt_manager = PromptManager(fallback_strategy=strategy)
        
        # 创建模拟的 API 客户端
        mock_client = Mock(spec=OpenDotaClient)
        
        # 创建 HybridSkillBuilder（传入 prompt_manager）
        builder = HybridSkillBuilder(
            client=mock_client,
            llm_enabled=True,
            prompt_manager=prompt_manager
        )
        
        # 验证 prompt_manager 被正确设置
        assert builder.prompt_manager is not None
        assert builder.prompt_manager == prompt_manager


class TestLangfuseIntegration:
    """测试与 Langfuse 的集成"""
    
    def test_langfuse_strategy_creation(self):
        """测试 Langfuse 策略的创建"""
        mock_client = Mock()
        strategy = LangfusePromptStrategy(langfuse_client=mock_client)
        
        assert strategy.client == mock_client
    
    def test_langfuse_fallback_to_local(self):
        """测试 Langfuse 失败时降级到本地"""
        config_dir = Path(__file__).parent.parent.parent / "config" / "prompts"
        
        if not config_dir.exists():
            pytest.skip("config/prompts 目录不存在")
        
        # 创建会失败的 Langfuse 策略
        mock_client = Mock()
        mock_client.get_prompt.side_effect = Exception("Langfuse 不可用")
        
        langfuse_strategy = LangfusePromptStrategy(langfuse_client=mock_client)
        local_strategy = LocalYAMLPromptStrategy(prompts_dir=str(config_dir))
        
        manager = PromptManager(
            primary_strategy=langfuse_strategy,
            fallback_strategy=local_strategy
        )
        
        # 应该降级到本地策略
        content = manager.get_prompt("assistant_system")
        assert content is not None
        assert "Dota 2" in content


class TestPromptVersionManagement:
    """测试 Prompt 版本管理功能"""
    
    def test_version_tracking(self):
        """测试版本追踪"""
        config_dir = Path(__file__).parent.parent.parent / "config" / "prompts"
        
        if not config_dir.exists():
            pytest.skip("config/prompts 目录不存在")
        
        strategy = LocalYAMLPromptStrategy(prompts_dir=str(config_dir))
        manager = PromptManager(fallback_strategy=strategy)
        
        # 获取 Prompt 元数据
        metadata = manager.get_prompt_metadata("assistant_system")
        
        # 验证版本信息
        assert "version" in metadata
        assert metadata["version"] == 1
    
    def test_multiple_versions_support(self):
        """测试多版本支持（通过模拟）"""
        # 创建包含多个版本的临时配置
        import tempfile
        import yaml
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建版本 1
            v1_content = {
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
            v2_content = {
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
            
            # 写入文件
            with open(Path(tmpdir) / "v1.yaml", 'w', encoding='utf-8') as f:
                yaml.dump(v1_content, f, allow_unicode=True)
            
            with open(Path(tmpdir) / "v2.yaml", 'w', encoding='utf-8') as f:
                yaml.dump(v2_content, f, allow_unicode=True)
            
            strategy = LocalYAMLPromptStrategy(prompts_dir=tmpdir)
            manager = PromptManager(fallback_strategy=strategy)
            
            # 获取最新版本（应该是版本 2）
            content_latest = manager.get_prompt("test_prompt")
            assert content_latest == "版本 2 内容"
            
            # 获取指定版本
            content_v1 = manager.get_prompt("test_prompt", version=1)
            assert content_v1 == "版本 1 内容"
            
            content_v2 = manager.get_prompt("test_prompt", version=2)
            assert content_v2 == "版本 2 内容"


class TestPromptRegistryIntegration:
    """测试 Prompt 注册表集成"""
    
    def test_registry_consistency(self):
        """测试注册表与实际文件的一致性"""
        import yaml
        
        config_dir = Path(__file__).parent.parent.parent / "config"
        prompt_config_path = config_dir / "prompt_config.yaml"
        prompts_dir = config_dir / "prompts"
        
        if not prompt_config_path.exists() or not prompts_dir.exists():
            pytest.skip("配置文件不存在")
        
        # 加载注册表配置
        with open(prompt_config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        registry = config.get("prompt_manager", {}).get("registry", {})
        
        # 验证注册表中的每个 Prompt 都在实际文件中存在
        strategy = LocalYAMLPromptStrategy(prompts_dir=str(prompts_dir))
        available_prompts = strategy.list_prompts()
        
        for prompt_name, yaml_file in registry.items():
            assert prompt_name in available_prompts, \
                f"注册表中的 Prompt '{prompt_name}' 在实际文件中不存在"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
