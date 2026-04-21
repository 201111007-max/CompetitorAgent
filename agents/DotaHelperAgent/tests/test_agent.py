"""Agent 核心功能测试"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent import DotaHelperAgent
from core.config import AgentConfig, MatchupConfig, CacheConfig


class TestDotaHelperAgentInit:
    """测试 Agent 初始化"""
    
    def test_init_default(self):
        """测试默认初始化"""
        agent = DotaHelperAgent()
        
        assert agent.config is None
        assert agent.client is not None
        assert agent.hero_analyzer is not None
        assert agent.item_recommender is not None
        assert agent.skill_builder is not None
    
    def test_init_with_config(self, agent_config):
        """测试使用自定义配置初始化"""
        agent = DotaHelperAgent(config=agent_config)
        
        assert agent.config == agent_config
        assert agent.client.config == agent_config
    
    def test_init_with_api_key(self):
        """测试使用 API Key 初始化"""
        agent = DotaHelperAgent(api_key="test_key")
        
        assert agent.client.api_key == "test_key"


class TestRecommendHeroes:
    """测试英雄推荐功能"""
    
    @patch('core.agent.OpenDotaClient')
    def test_recommend_heroes_basic(self, mock_client_class, mock_hero_data, mock_matchup_data):
        """测试基础英雄推荐"""
        mock_client = Mock()
        mock_client.get_heroes.return_value = mock_hero_data
        mock_client.get_hero_matchups.return_value = mock_matchup_data
        mock_client_class.return_value = mock_client
        
        agent = DotaHelperAgent()
        
        result = agent.recommend_heroes(
            our_heroes=["Anti-Mage"],
            enemy_heroes=["Pudge"],
            top_n=3
        )
        
        assert "our_team" in result
        assert "enemy_team" in result
        assert "recommendations" in result
        assert "composition_analysis" in result
        assert result["our_team"] == ["Anti-Mage"]
        assert result["enemy_team"] == ["Pudge"]
    
    @patch('core.agent.OpenDotaClient')
    def test_recommend_heroes_empty_lists(self, mock_client_class):
        """测试空列表输入"""
        mock_client = Mock()
        mock_client.get_heroes.return_value = []
        mock_client_class.return_value = mock_client
        
        agent = DotaHelperAgent()
        
        result = agent.recommend_heroes(
            our_heroes=[],
            enemy_heroes=[],
            top_n=3
        )
        
        assert result["recommendations"] == []


class TestRecommendBuild:
    """测试出装和技能推荐功能"""
    
    @patch('core.agent.OpenDotaClient')
    def test_recommend_build_basic(self, mock_client_class, mock_item_data):
        """测试基础出装推荐"""
        mock_client = Mock()
        mock_client.hero_name_to_id.return_value = 1
        mock_client.get_hero_item_popularity.return_value = mock_item_data
        mock_client_class.return_value = mock_client
        
        agent = DotaHelperAgent()
        
        result = agent.recommend_build(
            hero_name="Anti-Mage",
            role="core",
            game_stage="all"
        )
        
        assert result["hero"] == "Anti-Mage"
        assert result["role"] == "core"
        assert "items" in result
        assert "skills" in result
    
    @patch('core.agent.OpenDotaClient')
    def test_recommend_build_invalid_hero(self, mock_client_class):
        """测试无效英雄名称"""
        mock_client = Mock()
        mock_client.hero_name_to_id.return_value = None
        mock_client_class.return_value = mock_client
        
        agent = DotaHelperAgent()
        
        result = agent.recommend_build(
            hero_name="InvalidHero",
            role="core"
        )
        
        assert result["items"] == {}


class TestGetCounterHeroes:
    """测试克制英雄查询功能"""
    
    @patch('core.agent.OpenDotaClient')
    def test_get_counter_heroes(self, mock_client_class, mock_hero_data):
        """测试获取克制英雄"""
        mock_client = Mock()
        mock_client.get_heroes.return_value = mock_hero_data
        mock_client_class.return_value = mock_client
        
        agent = DotaHelperAgent()
        
        result = agent.get_counter_heroes(
            target_hero="Pudge",
            top_n=5
        )
        
        assert isinstance(result, list)


class TestFormatMethods:
    """测试格式化方法"""
    
    def test_format_recommendation(self):
        """测试格式化推荐结果"""
        agent = DotaHelperAgent()
        
        test_result = {
            "our_team": ["Anti-Mage", "Crystal Maiden"],
            "enemy_team": ["Pudge", "Phantom Assassin"],
            "recommendations": [
                {
                    "hero_name": "Axe",
                    "score": 85.5,
                    "reasons": [
                        "胜率 55.0%",
                        "出场 150 场"
                    ]
                }
            ],
            "composition_analysis": {
                "our_composition": "Core + Support",
                "enemy_composition": "Initiator + Carry"
            }
        }
        
        formatted = agent.format_recommendation(test_result)
        
        assert "Anti-Mage" in formatted
        assert "Axe" in formatted
        assert "55.0%" in formatted
        assert isinstance(formatted, str)
    
    def test_format_build(self):
        """测试格式化出装建议"""
        agent = DotaHelperAgent()
        
        test_build = {
            "hero": "Anti-Mage",
            "role": "core",
            "items": {
                "开局": [{"name": "Tango", "count": 500}],
                "中期": [{"name": "Battle Fury", "count": 1250}]
            },
            "skills": {
                "skill_order": ["Q", "W", "E"],
                "reasons": ["Max E for farming"]
            }
        }
        
        formatted = agent.format_build(test_build)
        
        assert "Anti-Mage" in formatted
        assert "Battle Fury" in formatted
        assert isinstance(formatted, str)


class TestCacheManagement:
    """测试缓存管理功能"""
    
    @patch('core.agent.OpenDotaClient')
    def test_warm_up_cache(self, mock_client_class):
        """测试缓存预热"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        agent = DotaHelperAgent()
        
        hero_ids = [1, 2, 5]
        agent.warm_up_cache(hero_ids=hero_ids)
        
        mock_client.warm_up_cache.assert_called_once_with(hero_ids)
    
    @patch('core.agent.OpenDotaClient')
    def test_clear_cache(self, mock_client_class):
        """测试清空缓存"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        agent = DotaHelperAgent()
        agent.clear_cache()
        
        mock_client.cache.clear.assert_called_once()


class TestIntegration:
    """集成测试"""
    
    @patch('core.agent.OpenDotaClient')
    def test_full_workflow(self, mock_client_class, mock_hero_data, mock_item_data):
        """测试完整工作流程"""
        mock_client = Mock()
        mock_client.get_heroes.return_value = mock_hero_data
        mock_client.get_hero_matchups.return_value = []
        mock_client.hero_name_to_id.return_value = 1
        mock_client.get_hero_item_popularity.return_value = mock_item_data
        mock_client_class.return_value = mock_client
        
        agent = DotaHelperAgent()
        
        result_heroes = agent.recommend_heroes(
            our_heroes=["Anti-Mage"],
            enemy_heroes=["Pudge"],
            top_n=3
        )
        
        result_build = agent.recommend_build(
            hero_name="Anti-Mage",
            role="core"
        )
        
        formatted_heroes = agent.format_recommendation(result_heroes)
        formatted_build = agent.format_build(result_build)
        
        assert isinstance(formatted_heroes, str)
        assert isinstance(formatted_build, str)
        assert len(formatted_heroes) > 0
        assert len(formatted_build) > 0
