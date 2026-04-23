"""API 客户端测试"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.api_client import OpenDotaClient
from core.config import AgentConfig, RateLimitConfig, CacheConfig


class TestOpenDotaClientInit:
    """测试客户端初始化"""
    
    def test_init_default(self):
        """测试默认初始化"""
        client = OpenDotaClient()
        
        assert client.api_key is None
        assert client.rate_limit_delay == 1.0
        assert client.cache is not None
        assert client._heroes_cache is None
    
    def test_init_with_api_key(self):
        """测试使用 API Key 初始化"""
        client = OpenDotaClient(api_key="test_key")
        
        assert client.api_key == "test_key"
    
    def test_init_with_config(self, agent_config):
        """测试使用配置初始化"""
        client = OpenDotaClient(config=agent_config)
        
        assert client.config == agent_config
        assert client.cache is not None
    
    def test_init_with_custom_delay(self):
        """测试自定义延迟"""
        client = OpenDotaClient(rate_limit_delay=0.5)
        
        assert client.rate_limit_delay == 0.5


class TestRateLimiting:
    """测试速率限制"""
    
    @pytest.mark.skip(reason="时间相关测试不稳定")
    @patch('utils.api_client.requests.Session')
    def test_rate_limit_delay(self, mock_session_class):
        """测试请求间隔"""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        client = OpenDotaClient(rate_limit_delay=0.1)
        
        client.get_heroes()
        first_request_time = client._last_request_time
        
        time.sleep(0.15)
        
        client.get_heroes()
        
        elapsed = client._last_request_time - first_request_time
        assert elapsed >= 0.1


class TestHeroMethods:
    """测试英雄相关方法"""
    
    @patch('utils.api_client.requests.Session')
    def test_get_heroes(self, mock_session_class):
        """测试获取英雄列表"""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.json.return_value = [
            {"id": 1, "name": "npc_dota_hero_antimage", "localized_name": "Anti-Mage"}
        ]
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        client = OpenDotaClient()
        heroes = client.get_heroes()
        
        assert isinstance(heroes, list)
        assert len(heroes) > 0
    
    @patch('utils.api_client.requests.Session')
    def test_get_heroes_with_cache(self, mock_session_class):
        """测试英雄列表缓存"""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.json.return_value = [
            {"id": 1, "name": "npc_dota_hero_antimage", "localized_name": "Anti-Mage"}
        ]
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        client = OpenDotaClient()
        
        heroes1 = client.get_heroes()
        heroes2 = client.get_heroes()
        
        assert heroes1 == heroes2
        assert client._heroes_cache is not None
    
    @patch('utils.api_client.requests.Session')
    def test_get_hero_matchups(self, mock_session_class):
        """测试获取英雄克制数据"""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.json.return_value = [
            {"hero_id": 2, "games_played": 150, "wins": 80}
        ]
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        client = OpenDotaClient()
        matchups = client.get_hero_matchups(1)
        
        assert isinstance(matchups, list)
    
    @patch('utils.api_client.requests.Session')
    def test_get_hero_item_popularity(self, mock_session_class):
        """测试获取物品热度数据"""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.json.return_value = {
            "start_game_items": {"item_tango": 500}
        }
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        client = OpenDotaClient()
        items = client.get_hero_item_popularity(1)
        
        assert isinstance(items, dict)


class TestCacheIntegration:
    """测试缓存集成"""
    
    @patch('utils.api_client.requests.Session')
    def test_heroes_cache(self, mock_session_class, temp_dir):
        """测试英雄列表缓存"""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.json.return_value = [
            {"id": 1, "localized_name": "Anti-Mage"}
        ]
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        client = OpenDotaClient(cache_dir=temp_dir)
        
        client.get_heroes()
        
        cached = client.cache.get("heroes_list")
        assert cached is not None
    
    @patch('utils.api_client.requests.Session')
    def test_matchups_cache(self, mock_session_class, temp_dir):
        """测试克制数据缓存"""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.json.return_value = [
            {"hero_id": 2, "games_played": 150, "wins": 80}
        ]
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        client = OpenDotaClient(cache_dir=temp_dir)
        
        client.get_hero_matchups(1)
        
        cached = client.cache.get("hero_matchups_1")
        assert cached is not None


class TestErrorHandling:
    """测试错误处理"""
    
    @patch('utils.api_client.requests.Session')
    def test_api_error(self, mock_session_class):
        """测试 API 错误"""
        mock_session = Mock()
        mock_session.get.side_effect = Exception("API Error")
        mock_session_class.return_value = mock_session
        
        client = OpenDotaClient()
        
        heroes = client.get_heroes()
        
        assert isinstance(heroes, list)
    
    @patch('utils.api_client.requests.Session')
    def test_timeout(self, mock_session_class):
        """测试超时"""
        mock_session = Mock()
        mock_session.get.side_effect = TimeoutError("Request timeout")
        mock_session_class.return_value = mock_session
        
        client = OpenDotaClient()
        
        heroes = client.get_heroes()
        
        assert isinstance(heroes, list)


class TestHeroConversion:
    """测试英雄转换方法"""
    
    @patch('utils.api_client.requests.Session')
    def test_hero_name_to_id(self, mock_session_class):
        """测试英雄名称转 ID"""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.json.return_value = [
            {"id": 1, "name": "npc_dota_hero_antimage", "localized_name": "Anti-Mage"}
        ]
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        client = OpenDotaClient()
        
        hero_id = client.hero_name_to_id("Anti-Mage")
        
        assert hero_id == 1
    
    @patch('utils.api_client.requests.Session')
    def test_hero_id_to_name(self, mock_session_class):
        """测试英雄 ID 转名称"""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.json.return_value = [
            {"id": 1, "name": "npc_dota_hero_antimage", "localized_name": "Anti-Mage"}
        ]
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        client = OpenDotaClient()
        
        hero_name = client.hero_id_to_name(1)
        
        assert hero_name == "Anti-Mage"
    
    @patch('utils.api_client.requests.Session')
    def test_hero_not_found(self, mock_session_class):
        """测试英雄未找到"""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        client = OpenDotaClient()
        
        hero_id = client.hero_name_to_id("InvalidHero")
        
        assert hero_id is None


class TestWarmUpCache:
    """测试缓存预热"""
    
    @patch('utils.api_client.requests.Session')
    def test_warm_up_cache(self, mock_session_class):
        """测试缓存预热"""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.json.return_value = [
            {"id": 1, "localized_name": "Anti-Mage"},
            {"id": 2, "localized_name": "Axe"},
        ]
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        client = OpenDotaClient()
        
        client.warm_up_cache(hero_ids=[1, 2])
        
        assert client._heroes_cache is not None
