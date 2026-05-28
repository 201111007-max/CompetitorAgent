"""BackgroundLoader 单元测试"""

import pytest
import time
import threading
from unittest.mock import Mock, MagicMock, patch

from utils.background_loader import BackgroundLoader, SmartBackgroundLoader


class TestBackgroundLoader:
    """BackgroundLoader 测试类"""
    
    @pytest.fixture
    def mock_matchup_manager(self):
        """创建模拟 MatchupDataManager"""
        manager = Mock()
        manager.save_matchup = Mock(return_value=True)
        return manager
    
    @pytest.fixture
    def mock_api_client(self):
        """创建模拟 API 客户端"""
        client = Mock()
        client.get_hero_matchups = Mock(return_value=[
            {"hero_id": 2, "wins": 100, "games_played": 200}
        ])
        return client
    
    @pytest.fixture
    def background_loader(self, mock_matchup_manager, mock_api_client):
        """创建 BackgroundLoader"""
        return BackgroundLoader(
            matchup_manager=mock_matchup_manager,
            api_client=mock_api_client,
            rate_limit=10.0,  # 测试时使用较高频率
            max_retries=1
        )
    
    def test_init(self, background_loader):
        """测试初始化"""
        assert background_loader is not None
        assert background_loader.rate_limit == 10.0
        assert background_loader.max_retries == 1
    
    def test_add_task(self, background_loader):
        """测试添加任务"""
        background_loader.add_task(hero_id=1, priority=0)
        
        stats = background_loader.get_stats()
        assert stats["total_tasks"] == 1
        assert background_loader.get_queue_size() == 1
    
    def test_add_batch_tasks(self, background_loader):
        """测试批量添加任务"""
        hero_ids = [1, 2, 3, 4, 5]
        background_loader.add_batch_tasks(hero_ids, priority=1)
        
        stats = background_loader.get_stats()
        assert stats["total_tasks"] == 5
        assert background_loader.get_queue_size() == 5
    
    def test_start_and_stop(self, background_loader):
        """测试启动和停止"""
        background_loader.start()
        assert background_loader.is_running() is True
        
        time.sleep(0.1)
        
        background_loader.stop()
        assert background_loader.is_running() is False
    
    def test_load_hero_matchup_success(self, background_loader, mock_api_client, mock_matchup_manager):
        """测试成功加载单个英雄"""
        hero_id = 1
        
        result = background_loader._load_hero_matchup(hero_id)
        
        assert result is True
        mock_api_client.get_hero_matchups.assert_called_once_with(hero_id)
        mock_matchup_manager.save_matchup.assert_called_once()
    
    def test_load_hero_matchup_failure(self, background_loader, mock_api_client):
        """测试加载失败"""
        hero_id = 999
        
        mock_api_client.get_hero_matchups = Mock(return_value=None)
        
        result = background_loader._load_hero_matchup(hero_id)
        
        assert result is False
    
    def test_get_stats(self, background_loader):
        """测试获取统计信息"""
        background_loader.add_task(hero_id=1)
        
        stats = background_loader.get_stats()
        
        assert "running" in stats
        assert "queue_size" in stats
        assert "total_tasks" in stats
        assert "completed_tasks" in stats
        assert "failed_tasks" in stats
    
    def test_clear_queue(self, background_loader):
        """测试清空队列"""
        background_loader.add_batch_tasks([1, 2, 3, 4, 5])
        
        assert background_loader.get_queue_size() == 5
        
        background_loader.clear_queue()
        
        assert background_loader.get_queue_size() == 0
    
    def test_priority_order(self, background_loader):
        """测试优先级顺序"""
        background_loader.add_task(hero_id=1, priority=2)
        background_loader.add_task(hero_id=2, priority=0)
        background_loader.add_task(hero_id=3, priority=1)
        
        queue_size = background_loader.get_queue_size()
        assert queue_size == 3
    
    def test_callback_on_complete(self, mock_matchup_manager, mock_api_client):
        """测试完成回调"""
        callback_results = []
        
        def on_complete(hero_id, success):
            callback_results.append((hero_id, success))
        
        loader = BackgroundLoader(
            matchup_manager=mock_matchup_manager,
            api_client=mock_api_client,
            rate_limit=10.0,
            on_complete_callback=on_complete
        )
        
        loader._load_hero_matchup(1)
        
        assert len(callback_results) == 1
        assert callback_results[0] == (1, True)


class TestSmartBackgroundLoader:
    """SmartBackgroundLoader 测试类"""
    
    @pytest.fixture
    def mock_matchup_manager(self):
        """创建模拟 MatchupDataManager"""
        manager = Mock()
        manager.save_matchup = Mock(return_value=True)
        return manager
    
    @pytest.fixture
    def mock_api_client(self):
        """创建模拟 API 客户端"""
        client = Mock()
        client.get_hero_matchups = Mock(return_value=[
            {"hero_id": 2, "wins": 100, "games_played": 200}
        ])
        return client
    
    @pytest.fixture
    def smart_loader(self, mock_matchup_manager, mock_api_client):
        """创建 SmartBackgroundLoader"""
        return SmartBackgroundLoader(
            matchup_manager=mock_matchup_manager,
            api_client=mock_api_client,
            rate_limit=10.0
        )
    
    def test_init(self, smart_loader):
        """测试初始化"""
        assert smart_loader is not None
        assert smart_loader._paused is False
        assert smart_loader._consecutive_failures == 0
    
    def test_pause_and_resume(self, smart_loader):
        """测试暂停和恢复"""
        smart_loader.pause()
        assert smart_loader._paused is True
        
        smart_loader.resume()
        assert smart_loader._paused is False
        assert smart_loader._consecutive_failures == 0
    
    def test_adaptive_rate_limit(self, smart_loader, mock_api_client):
        """测试自适应速率调整"""
        initial_rate = smart_loader._adaptive_rate_limit
        
        mock_api_client.get_hero_matchups = Mock(return_value=None)
        
        for _ in range(3):
            smart_loader._load_hero_matchup(1)
        
        assert smart_loader._consecutive_failures >= 3
        assert smart_loader._adaptive_rate_limit < initial_rate
    
    def test_get_stats(self, smart_loader):
        """测试获取增强统计信息"""
        stats = smart_loader.get_stats()
        
        assert "paused" in stats
        assert "consecutive_failures" in stats
        assert "adaptive_rate_limit" in stats


class TestBackgroundLoaderIntegration:
    """BackgroundLoader 集成测试"""
    
    def test_full_workflow(self):
        """测试完整工作流程"""
        mock_manager = Mock()
        mock_manager.save_matchup = Mock(return_value=True)
        
        mock_api = Mock()
        mock_api.get_hero_matchups = Mock(return_value=[
            {"hero_id": 2, "wins": 100}
        ])
        
        loader = BackgroundLoader(
            matchup_manager=mock_manager,
            api_client=mock_api,
            rate_limit=100.0,  # 高频率用于测试
            max_retries=1
        )
        
        loader.start()
        
        loader.add_task(hero_id=1, priority=0)
        
        time.sleep(0.2)
        
        loader.stop()
        
        stats = loader.get_stats()
        assert stats["completed_tasks"] >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])