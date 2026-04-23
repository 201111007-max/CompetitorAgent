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
    try:
        from utils.api_client import OpenDotaClient
        from utils.llm_client import LLMClient, LLMConfig, DotaLLMAnalyzer
        from analyzers.hero_analyzer import HeroAnalyzer
        from analyzers.item_recommender import ItemRecommender
        from analyzers.skill_builder import SkillBuilder
        from core.config import AgentConfig, MatchupConfig
    except ImportError:
        from agents.DotaHelperAgent.utils.api_client import OpenDotaClient
        from agents.DotaHelperAgent.utils.llm_client import LLMClient, LLMConfig, DotaLLMAnalyzer
        from agents.DotaHelperAgent.analyzers.hero_analyzer import HeroAnalyzer
        from agents.DotaHelperAgent.analyzers.item_recommender import ItemRecommender
        from agents.DotaHelperAgent.analyzers.skill_builder import SkillBuilder
        from agents.DotaHelperAgent.core.config import AgentConfig, MatchupConfig


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
        # 先尝试使用 LLM 分析
        if self.llm_enabled and self.llm_analyzer:
            try:
                llm_result = self.llm_analyzer.recommend_heroes(
                    our_heroes=our_heroes,
                    enemy_heroes=enemy_heroes,
                    top_n=top_n
                )
                if llm_result:
                    return {
                        "source": "llm",
                        "recommendations": llm_result,
                        "our_heroes": our_heroes,
                        "enemy_heroes": enemy_heroes
                    }
            except Exception as e:
                print(f"⚠️ LLM 分析失败: {e}")
                print("   回退到数据驱动模式")

        # 回退到数据驱动分析
        recommendations = self.hero_analyzer.analyze_matchups(
            our_heroes=our_heroes,
            enemy_heroes=enemy_heroes,
            top_n=top_n
        )
        return {
            "recommendations": recommendations,
            "source": "data",
            "our_heroes": our_heroes,
            "enemy_heroes": enemy_heroes
        }

    def recommend_items(
        self,
        hero_name: str,
        game_stage: str = "all",
        enemy_heroes: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """推荐出装

        Args:
            hero_name: 英雄名称
            game_stage: 游戏阶段
            enemy_heroes: 敌方英雄列表

        Returns:
            Dict: 出装推荐
        """
        return self.item_recommender.recommend_items(
            hero_name=hero_name,
            game_stage=game_stage,
            enemy_heroes=enemy_heroes or []
        )

    def recommend_skills(
        self,
        hero_name: str,
        role: str = "core",
        enemy_heroes: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """推荐技能加点

        Args:
            hero_name: 英雄名称
            role: 角色定位
            enemy_heroes: 敌方英雄列表

        Returns:
            Dict: 技能加点推荐
        """
        return self.skill_builder.recommend_skill_build(
            hero_name=hero_name,
            role=role,
            enemy_heroes=enemy_heroes or []
        )