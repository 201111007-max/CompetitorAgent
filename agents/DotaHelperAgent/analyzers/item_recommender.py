"""物品推荐模块 - LLM 优先，数据驱动兜底"""

from typing import List, Dict, Optional, Tuple, Any

# 支持两种导入方式：包导入和直接运行
try:
    from ..utils.api_client import OpenDotaClient
    from ..core.hybrid_base import HybridAnalyzer, ExecutionSource
except ImportError:
    from utils.api_client import OpenDotaClient
    from core.hybrid_base import HybridAnalyzer, ExecutionSource


class HybridItemRecommender(HybridAnalyzer):
    """混合模式物品推荐器
    
    LLM 优先策略：
    1. 优先使用 LLM 根据局势智能推荐出装
    2. LLM 失败时回退到数据驱动的热门物品推荐
    """
    
    def __init__(self, client: OpenDotaClient, llm_enabled: bool = False):
        """初始化混合推荐器
        
        Args:
            client: OpenDota API 客户端
            llm_enabled: 是否启用 LLM
        """
        super().__init__(llm_enabled)
        self.set_data_client(client)
        self.client = client  # 保持兼容性
        self._items_cache: Optional[Dict[int, Dict]] = None
    
    def recommend_items(
        self,
        hero_name: str,
        game_stage: str = "all",
        enemy_heroes: Optional[List[str]] = None,
        use_llm: Optional[bool] = None
    ) -> Dict[str, Any]:
        """推荐英雄出装
        
        Args:
            hero_name: 英雄名称
            game_stage: 游戏阶段 ("early", "mid", "late", "all")
            enemy_heroes: 敌方英雄列表（用于 LLM 分析）
            use_llm: 是否使用 LLM（可选）
            
        Returns:
            Dict: 各阶段物品推荐，包含 source 字段标识来源
        """
        input_data = {
            "hero_name": hero_name,
            "game_stage": game_stage,
            "enemy_heroes": enemy_heroes or []
        }
        
        return self.analyze(input_data, use_llm)
    
    def _execute_llm(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """使用 LLM 推荐出装
        
        Args:
            input_data: 包含 hero_name, game_stage, enemy_heroes
            
        Returns:
            LLM 生成的出装建议
        """
        if not self._llm_analyzer:
            raise Exception("LLM 分析器未初始化")
        
        hero_name = input_data["hero_name"]
        game_stage = input_data["game_stage"]
        enemy_heroes = input_data.get("enemy_heroes", [])
        
        # 使用 LLM 生成出装建议
        llm_suggestion = self._llm_analyzer.suggest_item_build(
            hero_name=hero_name,
            enemy_heroes=enemy_heroes,
            game_stage=game_stage
        )
        
        # 解析 LLM 返回的文本为结构化数据
        items = self._parse_llm_suggestion(llm_suggestion, hero_name, game_stage)
        
        return {
            "hero": hero_name,
            "game_stage": game_stage,
            "items": items,
            "llm_analysis": llm_suggestion
        }
    
    def _execute_data(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """数据驱动的物品推荐
        
        Args:
            input_data: 包含 hero_name, game_stage
            
        Returns:
            基于数据的物品推荐
        """
        hero_name = input_data["hero_name"]
        game_stage = input_data["game_stage"]
        
        hero_id = self.client.hero_name_to_id(hero_name)
        if not hero_id:
            return {"hero": hero_name, "items": {}, "error": "英雄 ID 转换失败"}
        
        item_data = self.client.get_hero_item_popularity(hero_id)
        if not item_data:
            return {"hero": hero_name, "items": {}, "error": "未获取到物品数据"}
        
        recommendations = {}
        
        # 开局物品
        if game_stage in ("all", "early"):
            start_items = item_data.get("start_game_items", {})
            recommendations["开局"] = self._parse_items(start_items, top_n=3)
        
        # 前期物品
        if game_stage in ("all", "early"):
            early_items = item_data.get("early_game_items", {})
            recommendations["前期"] = self._parse_items(early_items, top_n=5)
        
        # 中期物品
        if game_stage in ("all", "mid"):
            mid_items = item_data.get("mid_game_items", {})
            recommendations["中期"] = self._parse_items(mid_items, top_n=5)
        
        # 后期物品
        if game_stage in ("all", "late"):
            late_items = item_data.get("late_game_items", {})
            recommendations["后期"] = self._parse_items(late_items, top_n=5)
        
        return {
            "hero": hero_name,
            "game_stage": game_stage,
            "items": recommendations
        }
    
    def _parse_llm_suggestion(
        self,
        llm_text: str,
        hero_name: str,
        game_stage: str
    ) -> Dict[str, List[Dict]]:
        """解析 LLM 返回的出装建议
        
        简化处理，将 LLM 的文本建议按阶段分类
        TODO: 可以使用更复杂的 NLP 解析
        
        Args:
            llm_text: LLM 生成的文本
            hero_name: 英雄名称
            game_stage: 游戏阶段
            
        Returns:
            结构化的物品推荐
        """
        # 简化实现：返回 LLM 的文本分析，同时尝试从数据源补充
        # 理想情况下应该解析 LLM 文本提取物品名称
        
        # 获取数据驱动的推荐作为补充
        data_result = self._execute_data({
            "hero_name": hero_name,
            "game_stage": "all"
        })
        
        # 返回混合结果：LLM 分析 + 数据支撑
        return {
            "llm_suggestion": llm_text,
            "data_support": data_result.get("items", {})
        }
    
    def _parse_items(
        self,
        items_dict: Dict[str, int],
        top_n: int = 5
    ) -> List[Dict]:
        """解析物品数据（保持兼容性）
        
        Args:
            items_dict: 物品 ID -> 购买次数
            top_n: 返回前 N 个
            
        Returns:
            List[Dict]: 物品列表
        """
        if not items_dict:
            return []
        
        # 按购买次数排序
        sorted_items = sorted(
            items_dict.items(),
            key=lambda x: x[1],
            reverse=True
        )[:top_n]
        
        result = []
        for item_id, count in sorted_items:
            item_name = self._get_item_name(int(item_id))
            result.append({
                "item_id": int(item_id),
                "item_name": item_name,
                "popularity": count
            })
        
        return result
    
    def _get_item_name(self, item_id: int) -> str:
        """获取物品名称"""
        self._ensure_items_cache()
        item_data = self._items_cache.get(item_id)
        if item_data and "name" in item_data:
            return item_data["name"]
        return f"item_{item_id}"
    
    def _ensure_items_cache(self) -> None:
        """确保物品常量数据已缓存"""
        if self._items_cache is not None:
            return
        
        try:
            constants = self.client.get_constants()
            if constants and isinstance(constants, dict):
                self._items_cache = constants.get("items", {})
            else:
                self._items_cache = {}
        except (AttributeError, TypeError, ConnectionError):
            self._items_cache = {}


# 保持向后兼容的别名
ItemRecommender = HybridItemRecommender
