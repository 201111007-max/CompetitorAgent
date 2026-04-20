"""DotaHelperAgent - Dota 2 英雄推荐助手"""

from typing import List, Dict, Optional, Any

from ..utils.api_client import OpenDotaClient
from ..analyzers.hero_analyzer import HeroAnalyzer
from ..analyzers.item_recommender import ItemRecommender
from ..analyzers.skill_builder import SkillBuilder
from .config import AgentConfig, MatchupConfig


class DotaHelperAgent:
    """Dota 2 英雄推荐助手 Agent
    
    特性：
    - 支持配置化
    - 支持多种评分策略
    - 智能缓存
    - 速率限制
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        config: Optional[AgentConfig] = None
    ):
        """初始化 Agent

        Args:
            api_key: OpenDota API Key（可选）
            config: 配置对象（可选）
        """
        self.config = config
        self.client = OpenDotaClient(api_key=api_key, config=config)
        
        # 使用配置创建分析器
        matchup_config = config.matchup if config else None
        self.hero_analyzer = HeroAnalyzer(self.client, config=matchup_config)
        self.item_recommender = ItemRecommender(self.client)
        self.skill_builder = SkillBuilder(self.client)

    def recommend_heroes(
        self,
        our_heroes: List[str],
        enemy_heroes: List[str],
        top_n: int = 3
    ) -> Dict[str, Any]:
        """推荐英雄

        Args:
            our_heroes: 己方已选英雄列表
            enemy_heroes: 对方已选英雄列表
            top_n: 推荐数量

        Returns:
            Dict: 推荐结果
        """
        print("=" * 60)
        print("正在分析英雄克制关系...")
        print("=" * 60)

        recommendations = self.hero_analyzer.analyze_matchups(
            our_heroes=our_heroes,
            enemy_heroes=enemy_heroes,
            top_n=top_n
        )

        # 阵容分析
        composition = self.hero_analyzer.analyze_team_composition(
            our_heroes=our_heroes,
            enemy_heroes=enemy_heroes
        )

        return {
            "our_team": our_heroes,
            "enemy_team": enemy_heroes,
            "recommendations": recommendations,
            "composition_analysis": composition
        }

    def recommend_build(
        self,
        hero_name: str,
        role: str = "core",
        game_stage: str = "all"
    ) -> Dict[str, Any]:
        """推荐出装和加点

        Args:
            hero_name: 英雄名称
            role: 角色定位
            game_stage: 游戏阶段

        Returns:
            Dict: 出装和加点建议
        """
        print(f"\n正在获取 {hero_name} 的出装建议...")

        # 物品推荐
        items = self.item_recommender.recommend_items(
            hero_name=hero_name,
            game_stage=game_stage
        )

        # 技能加点
        skills = self.skill_builder.recommend_skill_build(
            hero_name=hero_name,
            role=role
        )

        return {
            "hero": hero_name,
            "role": role,
            "items": items,
            "skills": skills
        }

    def get_counter_heroes(
        self,
        target_hero: str,
        top_n: int = 5
    ) -> List[Dict[str, Any]]:
        """获取克制某个英雄的英雄列表

        Args:
            target_hero: 目标英雄名称
            top_n: 返回数量

        Returns:
            List[Dict]: 克制英雄列表
        """
        return self.hero_analyzer.get_counter_heroes(target_hero, top_n)

    def warm_up_cache(self, hero_ids: Optional[List[int]] = None) -> None:
        """预热缓存

        Args:
            hero_ids: 要预热的英雄 ID 列表（可选）
        """
        self.client.warm_up_cache(hero_ids)

    def clear_cache(self) -> None:
        """清空缓存"""
        self.client.cache.clear()

    def format_recommendation(self, result: Dict[str, Any]) -> str:
        """格式化推荐结果为可读字符串

        Args:
            result: recommend_heroes 的返回结果

        Returns:
            str: 格式化后的字符串
        """
        lines = []
        lines.append("\n" + "=" * 60)
        lines.append("🎮 Dota 2 英雄推荐结果")
        lines.append("=" * 60)

        # 己方阵容
        if result.get("our_team"):
            lines.append(f"\n📋 己方阵容: {', '.join(result['our_team'])}")

        # 敌方阵容
        if result.get("enemy_team"):
            lines.append(f"📋 敌方阵容: {', '.join(result['enemy_team'])}")

        # 推荐英雄
        lines.append("\n🏆 推荐英雄:")
        for i, rec in enumerate(result.get("recommendations", []), 1):
            lines.append(f"\n  {i}. {rec['hero_name']} (得分: {rec['score']})")
            lines.append(f"     推荐理由:")
            for reason in rec.get("reasons", []):
                lines.append(f"       • {reason}")

        # 阵容分析
        composition = result.get("composition_analysis", {})
        if composition:
            lines.append("\n📊 阵容分析:")
            lines.append(f"     己方: {composition.get('our_composition', 'N/A')}")
            lines.append(f"     敌方: {composition.get('enemy_composition', 'N/A')}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    def format_build(self, build: Dict[str, Any]) -> str:
        """格式化出装建议为可读字符串

        Args:
            build: recommend_build 的返回结果

        Returns:
            str: 格式化后的字符串
        """
        lines = []
        lines.append("\n" + "=" * 60)
        lines.append(f"🦸 {build['hero']} - {build['role']} 出装建议")
        lines.append("=" * 60)

        # 物品推荐
        items = build.get("items", {})
        if items:
            lines.append("\n📦 推荐出装:")
            for stage, item_list in items.items():
                lines.append(f"\n  【{stage}】")
                for item in item_list:
                    lines.append(f"    • {item['item_name']} (热度: {item['popularity']})")

        # 技能加点
        skills = build.get("skills", {})
        if skills:
            lines.append("\n🔮 技能加点:")
            lines.append(f"  前期: {skills.get('early_game', {}).get('notes', 'N/A')}")
            lines.append(f"  中期: {skills.get('mid_game', {}).get('notes', 'N/A')}")
            lines.append(f"  后期: {skills.get('late_game', {}).get('notes', 'N/A')}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)
