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
        
        assert isinstance(result, dict)
        assert "recommendations" in result
        assert "source" in result
        assert result["source"] == "data"
    
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


class TestRecommendItems:
    """测试物品推荐功能"""
    
    @patch('core.agent.OpenDotaClient')
    def test_recommend_items_basic(self, mock_client_class, mock_item_data):
        """测试基础物品推荐"""
        mock_client = Mock()
        mock_client.hero_name_to_id.return_value = 1
        mock_client.get_hero_item_popularity.return_value = mock_item_data
        mock_client_class.return_value = mock_client
        
        agent = DotaHelperAgent()
        
        result = agent.recommend_items(
            hero_name="Anti-Mage",
            game_stage="all"
        )
        
        assert isinstance(result, dict)
        assert "hero" in result or "items" in result
    
    @patch('core.agent.OpenDotaClient')
    def test_recommend_items_invalid_hero(self, mock_client_class):
        """测试无效英雄名称"""
        mock_client = Mock()
        mock_client.hero_name_to_id.return_value = None
        mock_client_class.return_value = mock_client
        
        agent = DotaHelperAgent()
        
        result = agent.recommend_items(
            hero_name="InvalidHero",
            game_stage="all"
        )
        
        assert isinstance(result, dict)


class TestRecommendSkills:
    """测试技能推荐功能"""
    
    @patch('core.agent.OpenDotaClient')
    def test_recommend_skills_basic(self, mock_client_class):
        """测试基础技能推荐"""
        mock_client = Mock()
        mock_client.hero_name_to_id.return_value = 1
        mock_client.get_hero_stats.return_value = [
            {
                "id": 1,
                "localized_name": "Anti-Mage",
                "attack_type": "Melee",
                "primary_attr": "agi",
                "roles": ["Carry", "Escape", "Nuker"]
            }
        ]
        mock_client_class.return_value = mock_client
        
        agent = DotaHelperAgent()
        
        result = agent.recommend_skills(
            hero_name="Anti-Mage",
            role="core"
        )
        
        assert isinstance(result, dict)
    
    @patch('core.agent.OpenDotaClient')
    def test_recommend_skills_invalid_hero(self, mock_client_class):
        """测试无效英雄名称"""
        mock_client = Mock()
        mock_client.hero_name_to_id.return_value = None
        mock_client_class.return_value = mock_client
        
        agent = DotaHelperAgent()
        
        result = agent.recommend_skills(
            hero_name="InvalidHero",
            role="core"
        )
        
        assert isinstance(result, dict)


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
        mock_client.get_hero_stats.return_value = [
            {
                "id": 1,
                "localized_name": "Anti-Mage",
                "attack_type": "Melee",
                "primary_attr": "agi",
                "roles": ["Carry", "Escape", "Nuker"]
            }
        ]
        mock_client_class.return_value = mock_client
        
        agent = DotaHelperAgent()
        
        result_heroes = agent.recommend_heroes(
            our_heroes=["Anti-Mage"],
            enemy_heroes=["Pudge"],
            top_n=3
        )
        
        result_items = agent.recommend_items(
            hero_name="Anti-Mage",
            game_stage="all"
        )
        
        result_skills = agent.recommend_skills(
            hero_name="Anti-Mage",
            role="core"
        )
        
        assert isinstance(result_heroes, dict)
        assert isinstance(result_items, dict)
        assert isinstance(result_skills, dict)
