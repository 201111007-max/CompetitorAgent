"""MatchupDataManager 单元测试

测试新增功能：
- 数据过期机制（TTL）
- 数据完整性校验
- 数据包装与 metadata
"""

import pytest
import time
import json
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
from pathlib import Path

from managers.matchup_data_manager import MatchupDataManager
from cache.cache_manager import CacheManager


class TestMatchupDataManager:
    """MatchupDataManager 测试类"""
    
    @pytest.fixture
    def mock_cache_manager(self):
        """创建模拟 CacheManager"""
        cache = Mock(spec=CacheManager)
        cache.get = Mock(return_value=None)
        cache.set = Mock(return_value=True)
        cache.delete = Mock(return_value=True)
        return cache
    
    @pytest.fixture
    def mock_api_client(self):
        """创建模拟 API 客户端"""
        client = Mock()
        client.get_hero_matchups = Mock(return_value=[
            {"hero_id": 2, "wins": 100, "games_played": 200},
            {"hero_id": 3, "wins": 150, "games_played": 300}
        ])
        return client
    
    @pytest.fixture
    def temp_data_dir(self, tmp_path):
        """创建临时数据目录"""
        data_dir = tmp_path / "matchups"
        data_dir.mkdir()
        return str(data_dir)
    
    @pytest.fixture
    def matchup_manager(self, mock_cache_manager, mock_api_client, temp_data_dir):
        """创建 MatchupDataManager"""
        return MatchupDataManager(
            cache_manager=mock_cache_manager,
            api_client=mock_api_client,
            data_dir=temp_data_dir,
            auto_load_on_startup=False,
            ttl_days=7
        )
    
    def test_init_with_ttl(self, matchup_manager):
        """测试初始化（带 TTL）"""
        assert matchup_manager is not None
        assert matchup_manager.ttl_days == 7
        assert matchup_manager.TOTAL_HEROES == 124
    
    def test_wrap_data_with_metadata_list(self, matchup_manager):
        """测试数据包装（列表格式）"""
        raw_data = [
            {"hero_id": 2, "wins": 100, "games_played": 200}
        ]
        
        wrapped_data = matchup_manager._wrap_data_with_metadata(raw_data)
        
        assert "matchup_data" in wrapped_data
        assert "_metadata" in wrapped_data
        assert wrapped_data["matchup_data"] == raw_data
        assert "created_at" in wrapped_data["_metadata"]
        assert wrapped_data["_metadata"]["ttl_days"] == 7
    
    def test_wrap_data_with_metadata_dict(self, matchup_manager):
        """测试数据包装（字典格式）"""
        raw_data = {
            "hero_id": 1,
            "matchup_data": [
                {"hero_id": 2, "wins": 100, "games_played": 200}
            ]
        }
        
        wrapped_data = matchup_manager._wrap_data_with_metadata(raw_data)
        
        assert "matchup_data" in wrapped_data
        assert "_metadata" in wrapped_data
    
    def test_is_data_expired_new_data(self, matchup_manager):
        """测试数据过期检查（新数据）"""
        new_data = {
            "matchup_data": [
                {"hero_id": 2, "wins": 100, "games_played": 200}
            ],
            "_metadata": {
                "created_at": datetime.now().isoformat(),
                "ttl_days": 7
            }
        }
        
        is_expired = matchup_manager._is_data_expired(new_data)
        assert is_expired is False
    
    def test_is_data_expired_old_data(self, matchup_manager):
        """测试数据过期检查（过期数据）"""
        old_date = datetime.now() - timedelta(days=8)
        old_data = {
            "matchup_data": [
                {"hero_id": 2, "wins": 100, "games_played": 200}
            ],
            "_metadata": {
                "created_at": old_date.isoformat(),
                "ttl_days": 7
            }
        }
        
        is_expired = matchup_manager._is_data_expired(old_data)
        assert is_expired is True
    
    def test_is_data_expired_no_metadata(self, matchup_manager):
        """测试数据过期检查（无 metadata）"""
        data_without_metadata = [
            {"hero_id": 2, "wins": 100, "games_played": 200}
        ]
        
        is_expired = matchup_manager._is_data_expired(data_without_metadata)
        assert is_expired is True
    
    def test_validate_data_integrity_valid(self, matchup_manager):
        """测试数据完整性校验（有效数据）"""
        valid_data = {
            "matchup_data": [
                {"hero_id": 2, "wins": 100, "games_played": 200},
                {"hero_id": 3, "wins": 150, "games_played": 300}
            ]
        }
        
        is_valid = matchup_manager._validate_data_integrity(valid_data)
        assert is_valid is True
    
    def test_validate_data_integrity_missing_fields(self, matchup_manager):
        """测试数据完整性校验（缺失字段）"""
        invalid_data = {
            "matchup_data": [
                {"hero_id": 2, "wins": 100}
            ]
        }
        
        is_valid = matchup_manager._validate_data_integrity(invalid_data)
        assert is_valid is False
    
    def test_validate_data_integrity_low_games(self, matchup_manager):
        """测试数据完整性校验（比赛场次不足）"""
        low_games_data = {
            "matchup_data": [
                {"hero_id": 2, "wins": 5, "games_played": 8}
            ]
        }
        
        is_valid = matchup_manager._validate_data_integrity(low_games_data)
        assert is_valid is False
    
    def test_validate_data_integrity_empty_data(self, matchup_manager):
        """测试数据完整性校验（空数据）"""
        empty_data = {
            "matchup_data": []
        }
        
        is_valid = matchup_manager._validate_data_integrity(empty_data)
        assert is_valid is False
    
    def test_save_matchup_with_metadata(self, matchup_manager, temp_data_dir):
        """测试保存数据（带 metadata）"""
        hero_id = 1
        raw_data = [
            {"hero_id": 2, "wins": 100, "games_played": 200}
        ]
        
        result = matchup_manager.save_matchup(hero_id, raw_data)
        
        assert result is True
        
        file_path = Path(temp_data_dir) / f"hero_{hero_id}.json"
        assert file_path.exists()
        
        saved_data = json.loads(file_path.read_text(encoding="utf-8"))
        assert "matchup_data" in saved_data
        assert "_metadata" in saved_data
        assert saved_data["_metadata"]["ttl_days"] == 7
    
    def test_get_matchup_expired_data(self, matchup_manager, mock_cache_manager, temp_data_dir):
        """测试获取过期数据"""
        hero_id = 1
        old_date = datetime.now() - timedelta(days=8)
        
        expired_data = {
            "matchup_data": [
                {"hero_id": 2, "wins": 100, "games_played": 200}
            ],
            "_metadata": {
                "created_at": old_date.isoformat(),
                "ttl_days": 7
            }
        }
        
        mock_cache_manager.get = Mock(return_value=expired_data)
        
        result = matchup_manager.get_matchup(hero_id)
        
        assert result is None
        mock_cache_manager.delete.assert_called()
    
    def test_get_matchup_invalid_data(self, matchup_manager, mock_cache_manager, temp_data_dir):
        """测试获取无效数据"""
        hero_id = 1
        
        invalid_data = {
            "matchup_data": [
                {"hero_id": 2, "wins": 100}
            ]
        }
        
        mock_cache_manager.get = Mock(return_value=invalid_data)
        
        result = matchup_manager.get_matchup(hero_id)
        
        assert result is None
        mock_cache_manager.delete.assert_called()
    
    def test_get_matchup_valid_data(self, matchup_manager, mock_cache_manager):
        """测试获取有效数据"""
        hero_id = 1
        
        valid_data = {
            "matchup_data": [
                {"hero_id": 2, "wins": 100, "games_played": 200}
            ],
            "_metadata": {
                "created_at": datetime.now().isoformat(),
                "ttl_days": 7
            }
        }
        
        mock_cache_manager.get = Mock(return_value=valid_data)
        
        result = matchup_manager.get_matchup(hero_id)
        
        assert result is not None
        assert result == valid_data
    
    def test_get_status_with_ttl(self, matchup_manager):
        """测试获取状态（包含 TTL 信息）"""
        status = matchup_manager.get_status()
        
        assert "ttl_days" in status
        assert status["ttl_days"] == 7
        assert "expired_heroes" in status
        assert "invalid_heroes" in status
    
    def test_delete_expired_data(self, matchup_manager, mock_cache_manager, temp_data_dir):
        """测试删除过期数据"""
        hero_id = 1
        
        file_path = Path(temp_data_dir) / f"hero_{hero_id}.json"
        file_path.write_text(json.dumps({"test": "data"}), encoding="utf-8")
        
        matchup_manager._delete_expired_data(hero_id)
        
        mock_cache_manager.delete.assert_called()
        assert not file_path.exists()
        assert matchup_manager._data_status["expired_heroes"] == 1
    
    def test_delete_invalid_data(self, matchup_manager, mock_cache_manager, temp_data_dir):
        """测试删除无效数据"""
        hero_id = 1
        
        file_path = Path(temp_data_dir) / f"hero_{hero_id}.json"
        file_path.write_text(json.dumps({"test": "data"}), encoding="utf-8")
        
        matchup_manager._delete_invalid_data(hero_id)
        
        mock_cache_manager.delete.assert_called()
        assert not file_path.exists()
        assert matchup_manager._data_status["invalid_heroes"] == 1
    
    def test_ttl_custom_days(self, mock_cache_manager, mock_api_client, temp_data_dir):
        """测试自定义 TTL 天数"""
        manager = MatchupDataManager(
            cache_manager=mock_cache_manager,
            api_client=mock_api_client,
            data_dir=temp_data_dir,
            auto_load_on_startup=False,
            ttl_days=3
        )
        
        assert manager.ttl_days == 3
        
        old_date = datetime.now() - timedelta(days=4)
        expired_data = {
            "matchup_data": [
                {"hero_id": 2, "wins": 100, "games_played": 200}
            ],
            "_metadata": {
                "created_at": old_date.isoformat(),
                "ttl_days": 3
            }
        }
        
        is_expired = manager._is_data_expired(expired_data)
        assert is_expired is True


class TestMatchupDataManagerIntegration:
    """MatchupDataManager 集成测试"""
    
    @pytest.fixture
    def real_cache_manager(self):
        """创建真实的 CacheManager"""
        from cache.cache_manager import CacheManager
        cache = CacheManager(
            cache_dir="test_cache",
            ttl_hours=24,
            max_size_mb=10,
            max_items=100
        )
        return cache
    
    @pytest.fixture
    def temp_data_dir(self, tmp_path):
        """创建临时数据目录"""
        data_dir = tmp_path / "matchups"
        data_dir.mkdir()
        return str(data_dir)
    
    def test_full_workflow(self, real_cache_manager, temp_data_dir):
        """测试完整工作流程"""
        mock_api_client = Mock()
        mock_api_client.get_hero_matchups = Mock(return_value=[
            {"hero_id": 2, "wins": 100, "games_played": 200}
        ])
        
        manager = MatchupDataManager(
            cache_manager=real_cache_manager,
            api_client=mock_api_client,
            data_dir=temp_data_dir,
            auto_load_on_startup=False,
            ttl_days=7
        )
        
        hero_id = 1
        raw_data = [
            {"hero_id": 2, "wins": 100, "games_played": 200}
        ]
        
        save_result = manager.save_matchup(hero_id, raw_data)
        assert save_result is True
        
        get_result = manager.get_matchup(hero_id)
        assert get_result is not None
        assert "matchup_data" in get_result
        assert "_metadata" in get_result
        
        status = manager.get_status()
        assert status["ttl_days"] == 7
        assert "loaded_heroes" in status
        assert "expired_heroes" in status
        assert "invalid_heroes" in status