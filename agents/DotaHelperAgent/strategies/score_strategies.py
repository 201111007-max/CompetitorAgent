"""评分策略模块"""

from typing import List, Dict, Tuple, Any
from abc import ABC, abstractmethod

from ..core.config import MatchupConfig


class IScoreStrategy(ABC):
    """评分策略接口"""
    
    @abstractmethod
    def calculate(self, matchup: Dict[str, Any], config: MatchupConfig) -> Tuple[float, List[str]]:
        """计算得分
        
        Args:
            matchup: 克制数据
            config: 配置
            
        Returns:
            (score, reasons): 得分和理由列表
        """
        pass


class WinRateStrategy(IScoreStrategy):
    """胜率评分策略"""
    
    def calculate(self, matchup: Dict[str, Any], config: MatchupConfig) -> Tuple[float, List[str]]:
        """基于胜率计算得分"""
        games = matchup.get("games_played", 0)
        wins = matchup.get("wins", 0)
        
        if games < config.min_games_threshold:
            return 0.0, []
        
        win_rate = wins / games
        if win_rate <= config.min_winrate_threshold:
            return 0.0, []
        
        score = (win_rate - 0.5) * config.score_weight
        reason = f"胜率 {win_rate:.1%}"
        
        return score, [reason]


class PopularityStrategy(IScoreStrategy):
    """热度评分策略"""
    
    def calculate(self, matchup: Dict[str, Any], config: MatchupConfig) -> Tuple[float, List[str]]:
        """基于出场率计算得分"""
        games = matchup.get("games_played", 0)
        
        # 出场越多，分数越高（表示数据越可靠）
        score = games * 0.01
        reason = f"出场 {games} 场"
        
        return score, [reason]
