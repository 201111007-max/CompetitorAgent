"""英雄相关 Tools"""

from typing import List, Dict, Any, Optional
from .base import Tool


class AnalyzeCounterPicksTool(Tool):
    """分析克制英雄 Tool"""

    def __init__(self, hero_analyzer, localization=None):
        super().__init__(
            name="analyze_counter_picks",
            description="分析英雄克制关系，推荐克制敌方的英雄。根据我方已选英雄和敌方阵容，返回推荐的英雄及其克制理由。",
            parameters={
                "our_heroes": List[str],
                "enemy_heroes": List[str],
                "top_n": int
            },
            func=self._analyze,
            category="hero_analysis"
        )
        self._analyzer = hero_analyzer
        self._localization = localization

    def _analyze(
        self,
        our_heroes: List[str],
        enemy_heroes: List[str],
        top_n: int = 3
    ) -> Dict[str, Any]:
        return self._analyzer.analyze_matchups(our_heroes, enemy_heroes, top_n)


class AnalyzeCompositionTool(Tool):
    """分析阵容平衡性 Tool"""

    def __init__(self, hero_analyzer, localization=None):
        super().__init__(
            name="analyze_composition",
            description="分析阵容的平衡性和协同性，检查阵容缺少的角色（控制、爆发、推进等），评估阵容整体强度。",
            parameters={
                "our_heroes": List[str],
                "enemy_heroes": List[str]
            },
            func=self._analyze,
            category="hero_analysis"
        )
        self._analyzer = hero_analyzer
        self._localization = localization

    def _analyze(
        self,
        our_heroes: List[str],
        enemy_heroes: List[str]
    ) -> Dict[str, Any]:
        return self._analyzer.analyze_composition(our_heroes, enemy_heroes)


class GetMetaHeroesTool(Tool):
    """获取版本强势英雄 Tool"""

    def __init__(self, client):
        super().__init__(
            name="get_meta_heroes",
            description="获取当前版本强势英雄列表，基于大数据统计返回当前版本的热门和强力英雄。",
            parameters={
                "limit": int
            },
            func=self._get_meta,
            category="hero_analysis"
        )
        self._client = client

    def _get_meta(self, limit: int = 10) -> Dict[str, Any]:
        heroes = self._client.get_heroes()
        if not heroes:
            return {"meta_heroes": [], "reason": "无法获取数据"}

        sorted_heroes = sorted(
            heroes,
            key=lambda h: h.get("pick_rate", 0) + h.get("win_rate", 0) * 0.5,
            reverse=True
        )[:limit]

        return {
            "meta_heroes": [
                {
                    "hero_id": h.get("id"),
                    "hero_name": h.get("name", "").replace("npc_dota_hero_", ""),
                    "pick_rate": h.get("pick_rate", 0),
                    "win_rate": h.get("win_rate", 0)
                }
                for h in sorted_heroes
            ]
        }


def create_hero_tools(hero_analyzer, client, localization=None) -> List[Tool]:
    """创建所有英雄相关 Tools"""
    return [
        AnalyzeCounterPicksTool(hero_analyzer, localization),
        AnalyzeCompositionTool(hero_analyzer, localization),
        GetMetaHeroesTool(client)
    ]