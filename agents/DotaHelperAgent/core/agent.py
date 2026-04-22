"""DotaHelperAgent - Dota 2 英雄推荐助手

全模块 LLM 优先，数据驱动兜底的混合模式实现
"""

from typing import List, Dict, Optional, Any

# 支持两种导入方式：包导入和直接运行
try:
    from ..utils.api_client import OpenDotaClient
    from ..utils.llm_client import LLMClient, LLMConfig, DotaLLMAnalyzer
    from ..analyzers.hero_analyzer import HeroAnalyzer
    from ..analyzers.item_recommender import ItemRecommender
    from ..analyzers.skill_builder import SkillBuilder
    from .config import AgentConfig, MatchupConfig
except ImportError:
    from utils.api_client import OpenDotaClient
    from utils.llm_client import LLMClient, LLMConfig, DotaLLMAnalyzer
    from analyzers.hero_analyzer import HeroAnalyzer
    from analyzers.item_recommender import ItemRecommender
    from analyzers.skill_builder import SkillBuilder
    from config import AgentConfig, MatchupConfig


class DotaHelperAgent:
    """Dota 2 英雄推荐助手 Agent

    特性：
    - 支持配置化
    - 支持多种评分策略
    - 智能缓存
    - 速率限制
    - LLM 增强分析（可选）
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        config: Optional[AgentConfig] = None,
        enable_llm: Optional[bool] = None
    ):
        """初始化 Agent

        Args:
            api_key: OpenDota API Key（可选）
            config: 配置对象（可选）
            enable_llm: 是否启用 LLM（可选，默认使用配置）
        """
        self.config = config
        self.client = OpenDotaClient(api_key=api_key, config=config)

        # 使用配置创建分析器（混合模式：LLM 优先，数据驱动兜底）
        matchup_config = config.matchup if config else None
        self.hero_analyzer = HeroAnalyzer(self.client, config=matchup_config)
        
        # 初始化 LLM 客户端（优先从配置文件加载）
        self.llm_enabled = False
        self.llm_analyzer = None

        if config and config.llm and config.llm.enabled:
            # 使用配置文件中的 LLM 配置
            llm_config = config.llm
            llm_client = LLMClient(llm_config)
            self.llm_analyzer = DotaLLMAnalyzer(llm_client)
            self.llm_enabled = True

            # 检查 LLM 服务是否可用
            if not llm_client.check_health():
                print(f"⚠️ 警告：LLM 服务不可用 ({config.llm.base_url})")
                print("   将使用纯数据驱动模式")
                self.llm_enabled = False

        if enable_llm is not None:
            self.llm_enabled = enable_llm
        
        # 创建混合模式推荐器（LLM 优先）
        self.item_recommender = ItemRecommender(self.client, llm_enabled=self.llm_enabled)
        self.skill_builder = SkillBuilder(self.client, llm_enabled=self.llm_enabled)
        
        # 为分析器设置 LLM 支持
        if self.llm_analyzer:
            self.hero_analyzer.set_llm_analyzer(self.llm_analyzer)
            self.item_recommender.set_llm_analyzer(self.llm_analyzer)
            self.skill_builder.set_llm_analyzer(self.llm_analyzer)

    def recommend_heroes(
        self,
        our_heroes: List[str],
        enemy_heroes: List[str],
        top_n: int = 3
    ) -> Dict[str, Any]:
        """推荐英雄（优先使用 LLM，数据驱动作为兜底）

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

        recommendations = None
        use_llm = False

        # 优先尝试使用 LLM 推荐
        if self.llm_enabled and self.llm_analyzer:
            try:
                print("🤖 使用 LLM 进行智能推荐...")
                recommendations = self.llm_analyzer.recommend_heroes(
                    our_heroes=our_heroes,
                    enemy_heroes=enemy_heroes,
                    top_n=top_n
                )
                use_llm = True
                print(f"✓ LLM 推荐成功，生成 {len(recommendations)} 个推荐")
            except Exception as e:
                print(f"⚠️ LLM 推荐失败：{e}")
                print("   切换到数据驱动模式作为兜底...")

        # 如果 LLM 失败或未启用，使用数据驱动模式作为兜底
        if not use_llm:
            print("📊 使用数据驱动模式进行分析...")
            recommendations = self.hero_analyzer.analyze_matchups(
                our_heroes=our_heroes,
                enemy_heroes=enemy_heroes,
                top_n=top_n
            )
            print(f"✓ 数据分析完成，生成 {len(recommendations)} 个推荐")

        # 阵容分析（使用数据驱动）
        composition = self.hero_analyzer.analyze_team_composition(
            our_heroes=our_heroes,
            enemy_heroes=enemy_heroes
        )

        result = {
            "our_team": our_heroes,
            "enemy_team": enemy_heroes,
            "recommendations": recommendations,
            "composition_analysis": composition,
            "source": "llm" if use_llm else "data"
        }

        return result

    def recommend_build(
        self,
        hero_name: str,
        role: str = "core",
        game_stage: str = "all",
        enemy_heroes: Optional[List[str]] = None,
        use_llm: Optional[bool] = None
    ) -> Dict[str, Any]:
        """推荐出装和加点（LLM 优先，数据驱动兜底）

        Args:
            hero_name: 英雄名称
            role: 角色定位
            game_stage: 游戏阶段
            enemy_heroes: 敌方英雄列表（用于 LLM 分析）
            use_llm: 是否使用 LLM（可选）

        Returns:
            Dict: 出装和加点建议
        """
        print(f"\n正在获取 {hero_name} 的出装建议...")

        # 物品推荐（LLM 优先）
        items = self.item_recommender.recommend_items(
            hero_name=hero_name,
            game_stage=game_stage,
            enemy_heroes=enemy_heroes,
            use_llm=use_llm
        )

        # 技能加点（LLM 优先）
        skills = self.skill_builder.recommend_skill_build(
            hero_name=hero_name,
            role=role,
            enemy_heroes=enemy_heroes,
            use_llm=use_llm
        )

        return {
            "hero": hero_name,
            "role": role,
            "items": items,
            "skills": skills,
            "items_source": items.get("source", "unknown"),
            "skills_source": skills.get("source_detail", "unknown")
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

    def explain_recommendation_with_llm(
        self,
        hero_name: str,
        enemy_heroes: List[str],
        win_rate: float,
        reasons: List[str]
    ) -> Optional[str]:
        """使用 LLM 解释推荐原因

        Args:
            hero_name: 推荐的英雄名称
            enemy_heroes: 敌方英雄列表
            win_rate: 胜率
            reasons: 推荐理由

        Returns:
            LLM 生成的解释，如果 LLM 未启用则返回 None
        """
        if not self.llm_enabled or not self.llm_analyzer:
            return None

        try:
            return self.llm_analyzer.explain_recommendation(
                hero_name=hero_name,
                enemy_heroes=enemy_heroes,
                win_rate=win_rate,
                reasons=reasons
            )
        except Exception as e:
            print(f"LLM 解释生成失败: {e}")
            return None

    def analyze_composition_with_llm(
        self,
        our_heroes: List[str],
        enemy_heroes: List[str]
    ) -> Optional[str]:
        """使用 LLM 分析阵容

        Args:
            our_heroes: 己方英雄列表
            enemy_heroes: 敌方英雄列表

        Returns:
            LLM 生成的分析，如果 LLM 未启用则返回 None
        """
        if not self.llm_enabled or not self.llm_analyzer:
            return None

        try:
            return self.llm_analyzer.analyze_team_composition(
                our_heroes=our_heroes,
                enemy_heroes=enemy_heroes
            )
        except Exception as e:
            print(f"LLM 阵容分析失败: {e}")
            return None

    def ask_llm(self, question: str, context: Optional[str] = None) -> Optional[str]:
        """向 LLM 提问

        Args:
            question: 问题
            context: 可选的上下文

        Returns:
            LLM 的回答，如果 LLM 未启用则返回 None
        """
        if not self.llm_enabled or not self.llm_analyzer:
            return None

        try:
            return self.llm_analyzer.answer_question(question, context)
        except Exception as e:
            print(f"LLM 问答失败: {e}")
            return None

    def is_llm_enabled(self) -> bool:
        """检查 LLM 是否已启用

        Returns:
            是否启用
        """
        return self.llm_enabled

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
