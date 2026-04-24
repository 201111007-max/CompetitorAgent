"""Agent Tools 工厂函数

将分析器、推荐器等封装为标准化的 Agent Tools，供 Agent Controller 使用
"""

from typing import List, Dict, Any, Optional
from .base import Tool


def create_hero_tools(hero_analyzer, client, localization=None) -> List[Tool]:
    """创建所有英雄分析相关的 Tools
    
    Args:
        hero_analyzer: 英雄分析器实例
        client: OpenDota API 客户端
        localization: 本地化工具（可选）
        
    Returns:
        Tool 列表
    """
    tools = []
    
    # 1. 克制分析工具
    tools.append(Tool(
        name="analyze_counter_picks",
        description="分析英雄克制关系，推荐克制敌方的英雄。根据我方已选英雄和敌方阵容，返回推荐的英雄及其克制理由。",
        parameters={
            "our_heroes": list,
            "enemy_heroes": list,
            "top_n": int
        },
        func=lambda our_heroes, enemy_heroes, top_n=3: hero_analyzer.analyze_matchups(
            our_heroes, enemy_heroes, top_n
        ),
        category="hero_analysis",
        examples=[
            "推荐克制敌方帕吉和斧王的英雄",
            "我们选了影魔，对面有宙斯和水晶，应该选什么英雄"
        ]
    ))
    
    # 2. 阵容分析工具
    tools.append(Tool(
        name="analyze_composition",
        description="分析阵容的平衡性和协同性，检查阵容缺少的角色（控制、爆发、推进等），评估阵容整体强度。",
        parameters={
            "our_heroes": list,
            "enemy_heroes": list
        },
        func=lambda our_heroes, enemy_heroes: hero_analyzer.analyze_composition(
            our_heroes, enemy_heroes
        ),
        category="hero_analysis",
        examples=[
            "分析我们的阵容是否合理",
            "我们选了这三个英雄，阵容怎么样"
        ]
    ))
    
    # 3. 版本强势英雄工具
    tools.append(Tool(
        name="get_meta_heroes",
        description="获取当前版本强势英雄列表，基于大数据统计返回当前版本的热门和强力英雄。",
        parameters={
            "limit": int
        },
        func=lambda limit=10: _get_meta_heroes(client, limit),
        category="hero_analysis",
        examples=[
            "当前版本什么英雄强势",
            "推荐几个版本之子"
        ]
    ))
    
    # 4. 英雄信息查询工具
    tools.append(Tool(
        name="get_hero_info",
        description="获取指定英雄的详细信息，包括属性、技能、天赋等。",
        parameters={
            "hero_name": str
        },
        func=lambda hero_name: _get_hero_info(client, hero_name),
        category="hero_analysis",
        examples=[
            "帕吉的技能是什么",
            "告诉我祈求者的详细信息"
        ]
    ))
    
    return tools


def create_item_tools(item_recommender, client, localization=None) -> List[Tool]:
    """创建所有物品推荐相关的 Tools
    
    Args:
        item_recommender: 物品推荐器实例
        client: OpenDota API 客户端
        localization: 本地化工具（可选）
        
    Returns:
        Tool 列表
    """
    tools = []
    
    # 1. 出装推荐工具
    tools.append(Tool(
        name="recommend_items",
        description="根据英雄和局势推荐合适的出装方案，包括出门装、中期装和后期神装。",
        parameters={
            "hero_name": str,
            "game_stage": str,
            "enemy_heroes": list
        },
        func=lambda hero_name, game_stage="all", enemy_heroes=None: item_recommender.recommend_items(
            hero_name, game_stage, enemy_heroes or []
        ),
        category="item_recommendation",
        examples=[
            "影魔应该怎么出装",
            "推荐一下敌法师的出装顺序"
        ]
    ))
    
    # 2. 核心装备推荐工具
    tools.append(Tool(
        name="recommend_core_items",
        description="推荐英雄的核心装备，包括主要输出装和关键功能装。",
        parameters={
            "hero_name": str
        },
        func=lambda hero_name: _recommend_core_items(item_recommender, hero_name),
        category="item_recommendation",
        examples=[
            "幻影刺客的核心装备是什么",
            "宙斯必出的装备有哪些"
        ]
    ))
    
    # 3. 针对性出装工具
    tools.append(Tool(
        name="recommend_situational_items",
        description="根据敌方阵容推荐针对性装备，如 BKB、吹风机、羊刀等。",
        parameters={
            "hero_name": str,
            "enemy_heroes": list
        },
        func=lambda hero_name, enemy_heroes: _recommend_situational_items(
            item_recommender, hero_name, enemy_heroes
        ),
        category="item_recommendation",
        examples=[
            "对面有五个法师，我应该出什么",
            "敌方物理很多，需要什么装备"
        ]
    ))
    
    return tools


def create_skill_tools(skill_builder, client, localization=None) -> List[Tool]:
    """创建所有技能加点相关的 Tools
    
    Args:
        skill_builder: 技能加点器实例
        client: OpenDota API 客户端
        localization: 本地化工具（可选）
        
    Returns:
        Tool 列表
    """
    tools = []
    
    # 1. 技能加点推荐工具
    tools.append(Tool(
        name="recommend_skills",
        description="推荐英雄的技能加点顺序，包括主升、副升和大招升级时机。",
        parameters={
            "hero_name": str,
            "play_style": str
        },
        func=lambda hero_name, play_style="standard": skill_builder.recommend_skills(
            hero_name, play_style
        ),
        category="skill_recommendation",
        examples=[
            "祈求者怎么加点",
            "推荐一下帕吉的技能顺序"
        ]
    ))
    
    # 2. 天赋树推荐工具
    tools.append(Tool(
        name="recommend_talents",
        description="推荐英雄的天赋树选择，根据局势和玩法风格提供不同级别的天赋建议。",
        parameters={
            "hero_name": str,
            "game_stage": str
        },
        func=lambda hero_name, game_stage="all": _recommend_talents(skill_builder, hero_name, game_stage),
        category="skill_recommendation",
        examples=[
            "影魔 10 级天赋选什么",
            "推荐一下水晶的天赋加点"
        ]
    ))
    
    return tools


def create_build_tools(item_recommender, skill_builder, client, localization=None) -> List[Tool]:
    """创建完整的出装和技能加点工具集合
    
    Args:
        item_recommender: 物品推荐器实例
        skill_builder: 技能加点器实例
        client: OpenDota API 客户端
        localization: 本地化工具（可选）
        
    Returns:
        Tool 列表
    """
    return (
        create_item_tools(item_recommender, client, localization) +
        create_skill_tools(skill_builder, client, localization)
    )


def create_all_tools(
    hero_analyzer=None,
    item_recommender=None,
    skill_builder=None,
    client=None,
    localization=None
) -> List[Tool]:
    """创建所有可用的 Agent Tools
    
    Args:
        hero_analyzer: 英雄分析器实例（可选）
        item_recommender: 物品推荐器实例（可选）
        skill_builder: 技能加点器实例（可选）
        client: OpenDota API 客户端（可选）
        localization: 本地化工具（可选）
        
    Returns:
        所有可用的 Tool 列表
    """
    all_tools = []
    
    if hero_analyzer and client:
        all_tools.extend(create_hero_tools(hero_analyzer, client, localization))
    
    if item_recommender and client:
        all_tools.extend(create_item_tools(item_recommender, client, localization))
    
    if skill_builder and client:
        all_tools.extend(create_skill_tools(skill_builder, client, localization))
    
    return all_tools


# 辅助函数实现
def _get_meta_heroes(client, limit: int = 10) -> Dict[str, Any]:
    """获取版本强势英雄"""
    heroes = client.get_heroes()
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
                "win_rate": h.get("win_rate", 0),
                "games_played": h.get("games_played", 0)
            }
            for h in sorted_heroes
        ]
    }


def _get_hero_info(client, hero_name: str) -> Dict[str, Any]:
    """获取英雄信息"""
    heroes = client.get_heroes()
    if not heroes:
        return {"error": "无法获取英雄列表"}
    
    # 查找匹配的英雄
    target_hero = None
    for hero in heroes:
        hero_id_name = hero.get("name", "").replace("npc_dota_hero_", "")
        if hero_id_name.lower() == hero_name.lower() or hero.get("localized_name", "").lower() == hero_name.lower():
            target_hero = hero
            break
    
    if not target_hero:
        return {"error": f"未找到英雄：{hero_name}"}
    
    return {
        "hero_id": target_hero.get("id"),
        "hero_name": target_hero.get("name", "").replace("npc_dota_hero_", ""),
        "localized_name": target_hero.get("localized_name"),
        "primary_attr": target_hero.get("primary_attr"),
        "attack_type": target_hero.get("attack_type"),
        "roles": target_hero.get("roles", [])
    }


def _recommend_core_items(item_recommender, hero_name: str) -> Dict[str, Any]:
    """推荐核心装备"""
    result = item_recommender.recommend_items(hero_name, "core", [])
    return {
        "hero_name": hero_name,
        "core_items": result.get("core_items", []),
        "reason": result.get("reason", "")
    }


def _recommend_situational_items(item_recommender, hero_name: str, enemy_heroes: List[str]) -> Dict[str, Any]:
    """推荐针对性装备"""
    result = item_recommender.recommend_items(hero_name, "situational", enemy_heroes)
    return {
        "hero_name": hero_name,
        "enemy_heroes": enemy_heroes,
        "situational_items": result.get("situational_items", []),
        "reason": result.get("reason", "")
    }


def _recommend_talents(skill_builder, hero_name: str, game_stage: str = "all") -> Dict[str, Any]:
    """推荐天赋树"""
    result = skill_builder.recommend_skills(hero_name, "talent", game_stage)
    return {
        "hero_name": hero_name,
        "talents": result.get("talents", []),
        "reason": result.get("reason", "")
    }
