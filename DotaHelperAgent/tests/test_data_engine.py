"""
数据驱动引擎单元测试

测试覆盖：
- 引擎初始化
- 出装推荐逻辑
- 策略推荐逻辑
- 英雄选择推荐
- 胜率预测
- 对线策略分析
"""

import pytest
from unittest.mock import Mock, MagicMock
from core.decision.data_engine import DataEngine, DataRecommendation


class TestDataEngine:
    """数据驱动引擎测试类"""
    
    def test_initialization(self):
        """测试引擎初始化"""
        engine = DataEngine()
        assert engine is not None
        assert engine.api_client is None
        assert engine.cache is None
    
    def test_set_api_client(self):
        """测试设置 API 客户端"""
        engine = DataEngine()
        mock_client = Mock()
        engine.set_api_client(mock_client)
        assert engine.api_client == mock_client
    
    def test_set_cache(self):
        """测试设置缓存"""
        engine = DataEngine()
        mock_cache = Mock()
        engine.set_cache(mock_cache)
        assert engine.cache == mock_cache
    
    def test_generate_recommendation_item_purchase(self):
        """测试出装推荐"""
        engine = DataEngine()
        mock_cache = Mock()
        engine.set_cache(mock_cache)
        
        # 模拟缓存返回数据
        mock_cache.get_matchups.return_value = [
            {"items": ["item1", "item2", "item3"], "won": True},
            {"items": ["item1", "item2", "item4"], "won": True},
            {"items": ["item1", "item3", "item5"], "won": False},
        ]
        
        game_state = {
            "hero_id": 1,
            "enemy_hero_ids": [2, 3, 4, 5]
        }
        
        result = engine.generate_recommendation("item_purchase", game_state)
        
        assert result is not None
        assert result.engine == "data"
        assert "推荐出装" in result.recommendation
        assert result.confidence > 0
        assert "matches_analyzed" in result.data
    
    def test_generate_recommendation_game_start(self):
        """测试游戏开始策略推荐"""
        engine = DataEngine()
        mock_cache = Mock()
        engine.set_cache(mock_cache)
        
        # 模拟缓存返回数据
        mock_cache.get_matchups.return_value = [
            {"won": True},
            {"won": True},
            {"won": False},
        ]
        mock_cache.get_advantage.return_value = 0.15  # 15% 优势
        
        game_state = {
            "hero_id": 1,
            "enemy_hero_ids": [2, 3, 4, 5]
        }
        
        result = engine.generate_recommendation("game_start", game_state)
        
        assert result is not None
        assert result.engine == "data"
        assert "预测胜率" in result.recommendation
        assert "win_rate" in result.data
        assert "lane_strategy" in result.data
    
    def test_generate_recommendation_hero_pick(self):
        """测试英雄选择推荐"""
        engine = DataEngine()
        mock_cache = Mock()
        engine.set_cache(mock_cache)
        
        # 模拟缓存返回克制英雄
        mock_cache.get_counters.return_value = [
            {"hero_name": "英雄A", "win_rate": 0.6},
            {"hero_name": "英雄B", "win_rate": 0.55},
        ]
        
        game_state = {
            "enemy_heroes": [2, 3]
        }
        
        result = engine.generate_recommendation("hero_pick", game_state)
        
        assert result is not None
        assert result.engine == "data"
        assert "推荐选择克制英雄" in result.recommendation
        assert "counters" in result.data
    
    def test_generate_recommendation_no_cache(self):
        """测试无缓存时返回 None"""
        engine = DataEngine()
        # 不设置缓存
        
        game_state = {"hero_id": 1}
        result = engine.generate_recommendation("item_purchase", game_state)
        
        assert result is None
    
    def test_generate_recommendation_unsupported_event(self):
        """测试不支持的事件类型"""
        engine = DataEngine()
        mock_cache = Mock()
        engine.set_cache(mock_cache)
        
        game_state = {"hero_id": 1}
        result = engine.generate_recommendation("unknown_event", game_state)
        
        assert result is None
    
    def test_predict_win_rate(self):
        """测试胜率预测"""
        engine = DataEngine()
        mock_cache = Mock()
        engine.set_cache(mock_cache)
        
        # 模拟缓存返回数据（2胜1负）
        mock_cache.get_matchups.return_value = [
            {"won": True},
            {"won": True},
            {"won": False},
        ]
        
        win_rate = engine._predict_win_rate(1, [2, 3])
        
        assert win_rate == pytest.approx(2/3, 0.01)
    
    def test_predict_win_rate_no_data(self):
        """测试无数据时返回默认胜率"""
        engine = DataEngine()
        mock_cache = Mock()
        engine.set_cache(mock_cache)
        mock_cache.get_matchups.return_value = []
        
        win_rate = engine._predict_win_rate(1, [2, 3])
        
        assert win_rate == 0.5
    
    def test_analyze_lane_strategy_advantage(self):
        """测试优势对线策略"""
        engine = DataEngine()
        mock_cache = Mock()
        engine.set_cache(mock_cache)
        mock_cache.get_advantage.return_value = 0.15  # 15% 优势
        
        strategy = engine._analyze_lane_strategy(1, [2, 3])
        
        assert "激进对线" in strategy
    
    def test_analyze_lane_strategy_disadvantage(self):
        """测试劣势对线策略"""
        engine = DataEngine()
        mock_cache = Mock()
        engine.set_cache(mock_cache)
        mock_cache.get_advantage.return_value = -0.15  # -15% 劣势
        
        strategy = engine._analyze_lane_strategy(1, [2, 3])
        
        assert "保守对线" in strategy
    
    def test_analyze_lane_strategy_even(self):
        """测试均势对线策略"""
        engine = DataEngine()
        mock_cache = Mock()
        engine.set_cache(mock_cache)
        mock_cache.get_advantage.return_value = 0.05  # 5% 优势
        
        strategy = engine._analyze_lane_strategy(1, [2, 3])
        
        assert "正常对线" in strategy
    
    def test_analyze_best_build(self):
        """测试最佳出装分析"""
        engine = DataEngine()
        
        matchups = [
            {"items": ["item1", "item2", "item3"], "won": True},
            {"items": ["item1", "item2", "item4"], "won": True},
            {"items": ["item1", "item3", "item5"], "won": False},
            {"items": ["item2", "item3", "item6"], "won": True},
            {"items": ["item1", "item2", "item7"], "won": True},
        ]
        
        best_build = engine._analyze_best_build(matchups)
        
        assert best_build is not None
        assert "items" in best_build
        assert "win_rate" in best_build
        assert len(best_build["items"]) <= 3
    
    def test_analyze_best_build_empty(self):
        """测试空数据出装分析"""
        engine = DataEngine()
        
        best_build = engine._analyze_best_build([])
        
        assert best_build is None


class TestDataRecommendation:
    """数据推荐结果测试类"""
    
    def test_creation(self):
        """测试推荐结果创建"""
        rec = DataRecommendation(
            engine="data",
            recommendation="测试推荐",
            confidence=0.8,
            data={"key": "value"}
        )
        
        assert rec.engine == "data"
        assert rec.recommendation == "测试推荐"
        assert rec.confidence == 0.8
        assert rec.data == {"key": "value"}
    
    def test_to_dict(self):
        """测试转换为字典"""
        rec = DataRecommendation(
            engine="data",
            recommendation="测试推荐",
            confidence=0.75,
            data={"win_rate": 0.6}
        )
        
        rec_dict = rec.to_dict()
        
        assert rec_dict["engine"] == "data"
        assert rec_dict["recommendation"] == "测试推荐"
        assert rec_dict["confidence"] == 0.75
        assert rec_dict["data"] == {"win_rate": 0.6}
    
    def test_default_data(self):
        """测试默认 data 字段"""
        rec = DataRecommendation(
            engine="data",
            recommendation="测试",
            confidence=0.5
        )
        
        assert rec.data == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
