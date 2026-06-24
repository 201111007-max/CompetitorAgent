"""
数据驱动引擎 - 基于历史对局数据的胜率预测和推荐

职责：
- 查询历史对局数据
- 分析英雄克制关系
- 预测胜率
- 推荐出装方案

数据来源：
- OpenDota API（历史对局数据）
- 本地缓存（HeroMatchupCache）
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class DataRecommendation:
    """数据驱动推荐结果"""
    engine: str = "data"
    recommendation: str = ""
    confidence: float = 0.0
    data: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.data is None:
            self.data = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "engine": self.engine,
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "data": self.data
        }


class DataEngine:
    """数据驱动引擎"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化数据引擎
        
        Args:
            config: 配置字典
        """
        self.config = config or {}
        self.api_client = None
        self.cache = None
        logger.info("数据驱动引擎初始化完成")
    
    def set_api_client(self, api_client):
        """
        设置 API 客户端
        
        Args:
            api_client: OpenDota API 客户端
        """
        self.api_client = api_client
        logger.info("数据引擎设置 API 客户端")
    
    def set_cache(self, cache):
        """
        设置缓存
        
        Args:
            cache: 英雄对局缓存
        """
        self.cache = cache
        logger.info("数据引擎设置缓存")
    
    def generate_recommendation(
        self,
        event: Any,
        game_state: Any
    ) -> Optional[DataRecommendation]:
        """
        生成推荐
        
        Args:
            event: GSI 事件对象
            game_state: 游戏状态（GameState 对象或字典）
        
        Returns:
            推荐结果，如果不适用返回 None
        """
        try:
            # 归一化 game_state 为字典
            game_state_dict = self._normalize_game_state(game_state)
            
            # 提取事件类型
            event_type = event.event_type if hasattr(event, 'event_type') else str(event)
            
            if event_type == "item_purchase":
                return self._recommend_item_build(game_state_dict)
            elif event_type == "game_start":
                return self._recommend_strategy(game_state_dict)
            elif event_type == "hero_pick":
                return self._recommend_hero_pick(game_state_dict)
            else:
                return None
        
        except Exception as e:
            logger.error(f"生成数据推荐失败: {e}")
            return None
    
    def _normalize_game_state(self, game_state: Any) -> Dict[str, Any]:
        """
        将游戏状态归一化为字典
        
        Args:
            game_state: GameState 对象或字典
        
        Returns:
            归一化后的字典
        """
        if game_state is None:
            return {}
        
        if isinstance(game_state, dict):
            return game_state
        
        # GameState 对象，转换为字典
        if hasattr(game_state, 'to_dict'):
            return game_state.to_dict()
        
        return {}
    
    def _recommend_item_build(self, game_state: Dict[str, Any]) -> Optional[DataRecommendation]:
        """
        推荐出装方案
        
        Args:
            game_state: 游戏状态
        
        Returns:
            出装推荐
        """
        if not self.cache:
            logger.warning("缓存未设置，无法推荐出装")
            return None
        
        hero_id = game_state.get("hero_id")
        enemy_hero_ids = game_state.get("enemy_hero_ids", [])
        
        if not hero_id:
            return None
        
        # 查询历史对局数据
        matchups = self.cache.get_matchups(hero_id, enemy_hero_ids)
        
        if not matchups:
            return None
        
        # 分析胜率最高的出装
        best_build = self._analyze_best_build(matchups)
        
        if not best_build:
            return None
        
        return DataRecommendation(
            engine="data",
            recommendation=f"根据 {len(matchups)} 场对局数据，推荐出装：{', '.join(best_build['items'][:3])}",
            confidence=best_build["win_rate"],
            data={
                "matches_analyzed": len(matchups),
                "win_rate": best_build["win_rate"],
                "items": best_build["items"]
            }
        )
    
    def _recommend_strategy(self, game_state: Dict[str, Any]) -> Optional[DataRecommendation]:
        """
        推荐对局策略
        
        Args:
            game_state: 游戏状态
        
        Returns:
            策略推荐
        """
        if not self.cache:
            logger.warning("缓存未设置，无法推荐策略")
            return None
        
        hero_id = game_state.get("hero_id")
        enemy_hero_ids = game_state.get("enemy_hero_ids", [])
        
        if not hero_id or not enemy_hero_ids:
            return None
        
        # 预测胜率
        win_rate = self._predict_win_rate(hero_id, enemy_hero_ids)
        
        # 分析对线策略
        lane_strategy = self._analyze_lane_strategy(hero_id, enemy_hero_ids)
        
        return DataRecommendation(
            engine="data",
            recommendation=f"预测胜率 {win_rate:.1%}，建议 {lane_strategy}",
            confidence=0.75,
            data={
                "win_rate": win_rate,
                "lane_strategy": lane_strategy,
                "hero_id": hero_id,
                "enemy_hero_ids": enemy_hero_ids
            }
        )
    
    def _recommend_hero_pick(self, game_state: Dict[str, Any]) -> Optional[DataRecommendation]:
        """
        推荐英雄选择
        
        Args:
            game_state: 游戏状态
        
        Returns:
            英雄推荐
        """
        if not self.cache:
            return None
        
        our_heroes = game_state.get("our_heroes", [])
        enemy_heroes = game_state.get("enemy_heroes", [])
        
        if not enemy_heroes:
            return None
        
        # 查询克制英雄
        counters = self.cache.get_counters(enemy_heroes, top_n=3)
        
        if not counters:
            return None
        
        counter_names = [c.get("hero_name", "未知") for c in counters]
        
        return DataRecommendation(
            engine="data",
            recommendation=f"推荐选择克制英雄：{', '.join(counter_names)}",
            confidence=0.7,
            data={
                "counters": counters,
                "enemy_heroes": enemy_heroes
            }
        )
    
    def _analyze_best_build(self, matchups: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        分析最佳出装
        
        Args:
            matchups: 对局数据列表
        
        Returns:
            最佳出装信息
        """
        if not matchups:
            return None
        
        # 统计出装频率和胜率
        item_stats = {}
        
        for match in matchups:
            items = match.get("items", [])
            won = match.get("won", False)
            
            for item in items:
                if item not in item_stats:
                    item_stats[item] = {"count": 0, "wins": 0}
                
                item_stats[item]["count"] += 1
                if won:
                    item_stats[item]["wins"] += 1
        
        # 计算胜率并排序
        item_win_rates = []
        for item, stats in item_stats.items():
            if stats["count"] >= 5:  # 至少出现5次
                win_rate = stats["wins"] / stats["count"]
                item_win_rates.append({
                    "item": item,
                    "win_rate": win_rate,
                    "count": stats["count"]
                })
        
        # 按胜率排序
        item_win_rates.sort(key=lambda x: x["win_rate"], reverse=True)
        
        # 取前3个物品
        top_items = [i["item"] for i in item_win_rates[:3]]
        avg_win_rate = sum(i["win_rate"] for i in item_win_rates[:3]) / len(item_win_rates[:3]) if item_win_rates else 0
        
        return {
            "items": top_items,
            "win_rate": avg_win_rate
        }
    
    def _predict_win_rate(self, hero_id: int, enemy_hero_ids: List[int]) -> float:
        """
        预测胜率
        
        Args:
            hero_id: 英雄 ID
            enemy_hero_ids: 敌方英雄 ID 列表
        
        Returns:
            预测胜率
        """
        if not self.cache:
            return 0.5
        
        # 查询对局数据
        matchups = self.cache.get_matchups(hero_id, enemy_hero_ids)
        
        if not matchups:
            return 0.5  # 默认胜率
        
        # 计算实际胜率
        wins = sum(1 for m in matchups if m.get("won", False))
        win_rate = wins / len(matchups)
        
        return win_rate
    
    def _analyze_lane_strategy(self, hero_id: int, enemy_hero_ids: List[int]) -> str:
        """
        分析对线策略
        
        Args:
            hero_id: 英雄 ID
            enemy_hero_ids: 敌方英雄 ID 列表
        
        Returns:
            对线策略建议
        """
        if not self.cache:
            return "正常对线"
        
        # 查询克制关系
        advantage = self.cache.get_advantage(hero_id, enemy_hero_ids)
        
        if advantage is None:
            return "正常对线"
        
        if advantage > 0.1:  # 优势大于10%
            return "激进对线，争取击杀"
        elif advantage < -0.1:  # 劣势大于10%
            return "保守对线，等待支援"
        else:
            return "正常对线，寻找机会"
