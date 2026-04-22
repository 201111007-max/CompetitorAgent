"""混合模式英雄分析器 - LLM 优先，数据驱动兜底"""

from typing import List, Dict, Optional, Any

# 支持两种导入方式：包导入和直接运行
try:
    from ..utils.api_client import OpenDotaClient
    from ..core.hybrid_base import HybridAnalyzer, ExecutionSource
    from .hero_analyzer import HeroAnalyzer
except ImportError:
    from utils.api_client import OpenDotaClient
    from core.hybrid_base import HybridAnalyzer, ExecutionSource
    from hero_analyzer import HeroAnalyzer


class HybridHeroAnalyzer(HybridAnalyzer):
    """混合模式英雄分析器
    
    LLM 优先策略：
    1. 优先使用 LLM 进行英雄推荐和阵容分析
    2. LLM 失败时回退到数据驱动的克制分析
    """
    
    def __init__(self, client: OpenDotaClient, llm_enabled: bool = False):
        """初始化混合分析器
        
        Args:
            client: OpenDota API 客户端
            llm_enabled: 是否启用 LLM
        """
        super().__init__(llm_enabled)
        self.set_data_client(client)
        self.client = client
        
        # 内部使用原有的 HeroAnalyzer 作为数据驱动引擎
        self._data_analyzer = HeroAnalyzer(client)
    
    def recommend_heroes(
        self,
        our_heroes: List[str],
        enemy_heroes: List[str],
        top_n: int = 3,
        use_llm: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """推荐英雄
        
        Args:
            our_heroes: 己方已选英雄
            enemy_heroes: 敌方已选英雄
            top_n: 推荐数量
            use_llm: 是否使用 LLM
            
        Returns:
            推荐英雄列表
        """
        input_data = {
            "our_heroes": our_heroes,
            "enemy_heroes": enemy_heroes,
            "top_n": top_n
        }
        
        result = self.analyze(input_data, use_llm)
        return result.get("recommendations", [])
    
    def _execute_llm(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """使用 LLM 推荐英雄
        
        Args:
            input_data: 包含 our_heroes, enemy_heroes, top_n
            
        Returns:
            LLM 生成的推荐
        """
        if not self._llm_analyzer:
            raise Exception("LLM 分析器未初始化")
        
        our_heroes = input_data["our_heroes"]
        enemy_heroes = input_data["enemy_heroes"]
        top_n = input_data["top_n"]
        
        # 使用 LLM 推荐
        recommendations = self._llm_analyzer.recommend_heroes(
            our_heroes=our_heroes,
            enemy_heroes=enemy_heroes,
            top_n=top_n
        )
        
        return {
            "recommendations": recommendations,
            "source_detail": "llm"
        }
    
    def _execute_data(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """数据驱动的英雄推荐
        
        Args:
            input_data: 包含 our_heroes, enemy_heroes, top_n
            
        Returns:
            基于数据的推荐
        """
        our_heroes = input_data["our_heroes"]
        enemy_heroes = input_data["enemy_heroes"]
        top_n = input_data["top_n"]
        
        # 使用原有的 HeroAnalyzer
        recommendations = self._data_analyzer.analyze_matchups(
            our_heroes=our_heroes,
            enemy_heroes=enemy_heroes,
            top_n=top_n
        )
        
        return {
            "recommendations": recommendations,
            "source_detail": "data"
        }
    
    def analyze_composition(
        self,
        our_heroes: List[str],
        enemy_heroes: List[str],
        use_llm: Optional[bool] = None
    ) -> Dict[str, Any]:
        """分析阵容
        
        Args:
            our_heroes: 己方英雄
            enemy_heroes: 敌方英雄
            use_llm: 是否使用 LLM
            
        Returns:
            阵容分析结果
        """
        input_data = {
            "our_heroes": our_heroes,
            "enemy_heroes": enemy_heroes
        }
        
        # 优先尝试 LLM
        if use_llm is not False and self.llm_enabled and self._llm_analyzer:
            try:
                llm_analysis = self._llm_analyzer.analyze_team_composition(
                    our_heroes=our_heroes,
                    enemy_heroes=enemy_heroes
                )
                
                return {
                    "analysis": llm_analysis,
                    "source": "llm",
                    "success": True
                }
            except Exception as e:
                print(f"⚠️ LLM 阵容分析失败：{e}")
                print("   切换到数据驱动模式...")
        
        # 数据驱动兜底
        data_analysis = self._data_analyzer.analyze_team_composition(
            our_heroes=our_heroes,
            enemy_heroes=enemy_heroes
        )
        
        return {
            "analysis": data_analysis,
            "source": "data",
            "success": True
        }


# 保持向后兼容
HeroAnalyzer = HybridHeroAnalyzer
