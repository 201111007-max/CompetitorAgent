"""出装和技能相关 Tools"""

from typing import List, Dict, Any, Optional
from .base import Tool


class RecommendItemsTool(Tool):
    """推荐物品 Tool"""

    def __init__(self, item_recommender):
        super().__init__(
            name="recommend_items",
            description="根据英雄名称和游戏阶段推荐出装。可以根据敌方阵容调整出装策略。",
            parameters={
                "hero_name": str,
                "game_stage": str,
                "enemy_heroes": List[str]
            },
            func=self._recommend,
            category="build_recommendation"
        )
        self._recommender = item_recommender

    def _recommend(
        self,
        hero_name: str,
        game_stage: str = "all",
        enemy_heroes: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        return self._recommender.recommend_items(
            hero_name=hero_name,
            game_stage=game_stage,
            enemy_heroes=enemy_heroes or []
        )


class RecommendSkillsTool(Tool):
    """推荐技能加点 Tool"""

    def __init__(self, skill_builder):
        super().__init__(
            name="recommend_skills",
            description="根据英雄定位推荐技能加点顺序。考虑对线、团战等不同场景的加点策略。",
            parameters={
                "hero_name": str,
                "role": str,
                "enemy_heroes": List[str]
            },
            func=self._recommend,
            category="build_recommendation"
        )
        self._builder = skill_builder

    def _recommend(
        self,
        hero_name: str,
        role: str = "core",
        enemy_heroes: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        return self._builder.recommend_skill_build(
            hero_name=hero_name,
            role=role,
            enemy_heroes=enemy_heroes or []
        )


def create_build_tools(item_recommender, skill_builder) -> List[Tool]:
    """创建所有出装和技能相关 Tools"""
    return [
        RecommendItemsTool(item_recommender),
        RecommendSkillsTool(skill_builder)
    ]