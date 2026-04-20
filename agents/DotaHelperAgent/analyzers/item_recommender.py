"""物品推荐模块"""

from typing import List, Dict, Optional, Tuple
from dotaconstants import items
from ..utils.api_client import OpenDotaClient


class ItemRecommender:
    """物品出装推荐器"""

    # 游戏阶段定义（分钟）
    EARLY_GAME = 15
    MID_GAME = 30

    def __init__(self, client: OpenDotaClient):
        self.client = client

    def recommend_items(
        self,
        hero_name: str,
        game_stage: str = "all"
    ) -> Dict[str, List[Dict]]:
        """推荐英雄出装

        Args:
            hero_name: 英雄名称
            game_stage: 游戏阶段 ("early", "mid", "late", "all")

        Returns:
            Dict: 各阶段物品推荐
        """
        hero_id = self.client.hero_name_to_id(hero_name)
        if not hero_id:
            return {}

        item_data = self.client.get_hero_item_popularity(hero_id)
        if not item_data:
            return {}

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

        return recommendations

    def _parse_items(
        self,
        items_dict: Dict[str, int],
        top_n: int = 5
    ) -> List[Dict]:
        """解析物品数据

        Args:
            items_dict: 物品ID -> 购买次数
            top_n: 返回前N个

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
        item_data = items.get(item_id)
        if item_data and "name" in item_data:
            return item_data["name"]
        return f"item_{item_id}"
