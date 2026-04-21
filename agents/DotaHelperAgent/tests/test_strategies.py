"""评分策略测试"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.score_strategies import (
    IScoreStrategy,
    WinRateStrategy,
    PopularityStrategy
)
from core.config import MatchupConfig


class TestWinRateStrategy:
    """测试胜率评分策略"""
    
    def test_basic_calculation(self):
        """测试基础胜率计算"""
        strategy = WinRateStrategy()
        config = MatchupConfig(
            min_games_threshold=100,
            min_winrate_threshold=0.52,
            score_weight=100.0
        )
        
        matchup = {
            "games_played": 150,
            "wins": 80
        }
        
        score, reasons = strategy.calculate(matchup, config)
        
        expected_winrate = 80 / 150
        expected_score = (expected_winrate - 0.5) * 100.0
        
        assert score == pytest.approx(expected_score, rel=1e-5)
        assert len(reasons) > 0
        assert "胜率" in reasons[0]
    
    def test_below_threshold_games(self):
        """测试低于场次阈值"""
        strategy = WinRateStrategy()
        config = MatchupConfig(
            min_games_threshold=100,
            min_winrate_threshold=0.52
        )
        
        matchup = {
            "games_played": 50,
            "wins": 40
        }
        
        score, reasons = strategy.calculate(matchup, config)
        
        assert score == 0.0
        assert len(reasons) == 0
    
    def test_below_threshold_winrate(self):
        """测试低于胜率阈值"""
        strategy = WinRateStrategy()
        config = MatchupConfig(
            min_games_threshold=100,
            min_winrate_threshold=0.52
        )
        
        matchup = {
            "games_played": 150,
            "wins": 70
        }
        
        score, reasons = strategy.calculate(matchup, config)
        
        winrate = 70 / 150
        assert winrate < 0.52
        assert score == 0.0
        assert len(reasons) == 0
    
    def test_exact_threshold(self):
        """测试刚好达到阈值"""
        strategy = WinRateStrategy()
        config = MatchupConfig(
            min_games_threshold=100,
            min_winrate_threshold=0.52
        )
        
        matchup = {
            "games_played": 100,
            "wins": 52
        }
        
        score, reasons = strategy.calculate(matchup, config)
        
        winrate = 52 / 100
        assert winrate == 0.52
        assert score == 0.0
        assert len(reasons) > 0
    
    def test_high_winrate(self):
        """测试高胜率"""
        strategy = WinRateStrategy()
        config = MatchupConfig(
            min_games_threshold=100,
            min_winrate_threshold=0.52,
            score_weight=100.0
        )
        
        matchup = {
            "games_played": 200,
            "wins": 150
        }
        
        score, reasons = strategy.calculate(matchup, config)
        
        expected_winrate = 150 / 200
        expected_score = (expected_winrate - 0.5) * 100.0
        
        assert score == pytest.approx(expected_score, rel=1e-5)
        assert score > 0
    
    def test_custom_weight(self):
        """测试自定义权重"""
        strategy = WinRateStrategy()
        config = MatchupConfig(
            min_games_threshold=100,
            min_winrate_threshold=0.52,
            score_weight=50.0
        )
        
        matchup = {
            "games_played": 150,
            "wins": 90
        }
        
        score, reasons = strategy.calculate(matchup, config)
        
        winrate = 90 / 150
        expected_score = (winrate - 0.5) * 50.0
        
        assert score == pytest.approx(expected_score, rel=1e-5)


class TestPopularityStrategy:
    """测试热度评分策略"""
    
    def test_basic_calculation(self):
        """测试基础热度计算"""
        strategy = PopularityStrategy()
        config = MatchupConfig()
        
        matchup = {
            "games_played": 150
        }
        
        score, reasons = strategy.calculate(matchup, config)
        
        expected_score = 150 * 0.01
        
        assert score == pytest.approx(expected_score, rel=1e-5)
        assert len(reasons) > 0
        assert "出场" in reasons[0]
        assert "150" in reasons[0]
    
    def test_zero_games(self):
        """测试零场次"""
        strategy = PopularityStrategy()
        config = MatchupConfig()
        
        matchup = {
            "games_played": 0
        }
        
        score, reasons = strategy.calculate(matchup, config)
        
        assert score == 0.0
        assert len(reasons) > 0
    
    def test_high_popularity(self):
        """测试高热度"""
        strategy = PopularityStrategy()
        config = MatchupConfig()
        
        matchup = {
            "games_played": 1000
        }
        
        score, reasons = strategy.calculate(matchup, config)
        
        expected_score = 1000 * 0.01
        
        assert score == pytest.approx(expected_score, rel=1e-5)
        assert score > 0
    
    def test_reason_format(self):
        """测试理由格式"""
        strategy = PopularityStrategy()
        config = MatchupConfig()
        
        matchup = {
            "games_played": 250
        }
        
        score, reasons = strategy.calculate(matchup, config)
        
        assert len(reasons) == 1
        assert "250" in reasons[0]


class TestStrategyIntegration:
    """策略集成测试"""
    
    def test_multiple_strategies(self):
        """测试多个策略组合"""
        winrate_strategy = WinRateStrategy()
        popularity_strategy = PopularityStrategy()
        
        config = MatchupConfig(
            min_games_threshold=100,
            min_winrate_threshold=0.52,
            score_weight=100.0
        )
        
        matchup = {
            "games_played": 150,
            "wins": 80
        }
        
        winrate_score, winrate_reasons = winrate_strategy.calculate(matchup, config)
        popularity_score, popularity_reasons = popularity_strategy.calculate(matchup, config)
        
        total_score = winrate_score + popularity_score
        all_reasons = winrate_reasons + popularity_reasons
        
        assert total_score > 0
        assert len(all_reasons) == 2
        assert any("胜率" in r for r in all_reasons)
        assert any("出场" in r for r in all_reasons)
    
    def test_strategy_with_edge_cases(self):
        """测试边界情况"""
        winrate_strategy = WinRateStrategy()
        popularity_strategy = PopularityStrategy()
        
        config = MatchupConfig(
            min_games_threshold=100,
            min_winrate_threshold=0.52
        )
        
        test_cases = [
            {
                "matchup": {"games_played": 100, "wins": 52},
                "description": "刚好达到阈值"
            },
            {
                "matchup": {"games_played": 99, "wins": 60},
                "description": "场次不足"
            },
            {
                "matchup": {"games_played": 200, "wins": 90},
                "description": "胜率不足"
            },
            {
                "matchup": {"games_played": 500, "wins": 300},
                "description": "高胜率高出场"
            }
        ]
        
        for case in test_cases:
            matchup = case["matchup"]
            
            winrate_score, winrate_reasons = winrate_strategy.calculate(matchup, config)
            popularity_score, popularity_reasons = popularity_strategy.calculate(matchup, config)
            
            assert isinstance(winrate_score, float)
            assert isinstance(popularity_score, float)
            assert isinstance(winrate_reasons, list)
            assert isinstance(popularity_reasons, list)


class TestStrategyInterface:
    """测试策略接口"""
    
    def test_interface_implementation(self):
        """测试接口实现"""
        winrate_strategy = WinRateStrategy()
        popularity_strategy = PopularityStrategy()
        
        assert isinstance(winrate_strategy, IScoreStrategy)
        assert isinstance(popularity_strategy, IScoreStrategy)
    
    def test_abstract_method(self):
        """测试抽象方法"""
        config = MatchupConfig()
        matchup = {"games_played": 100, "wins": 55}
        
        winrate_strategy = WinRateStrategy()
        result = winrate_strategy.calculate(matchup, config)
        
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], (int, float))
        assert isinstance(result[1], list)
