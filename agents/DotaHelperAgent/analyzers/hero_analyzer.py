"""英雄克制分析模块"""

from typing import List, Dict, Tuple, Optional, Any

# 支持两种导入方式：包导入和直接运行
try:
    from ..utils.api_client import OpenDotaClient
    from ..core.config import MatchupConfig
    from ..strategies.score_strategies import IScoreStrategy, WinRateStrategy
except ImportError:
    from utils.api_client import OpenDotaClient
    from core.config import MatchupConfig
    from strategies.score_strategies import IScoreStrategy, WinRateStrategy


class HeroAnalyzer:
    """英雄克制关系分析器"""
    
    def __init__(self, client: OpenDotaClient, config: Optional[MatchupConfig] = None):
        """初始化分析器
        
        Args:
            client: OpenDota API 客户端
            config: 配置（可选，使用默认配置）
        """
        self.client = client
        self.config = config or MatchupConfig()
        self._strategies: List[IScoreStrategy] = [WinRateStrategy()]
    
    def add_strategy(self, strategy: IScoreStrategy) -> None:
        """添加评分策略
        
        Args:
            strategy: 评分策略实例
        """
        self._strategies.append(strategy)
    
    def _analyze_single_matchup(
        self,
        hero_id: int,
        enemy_id: int
    ) -> Tuple[float, List[str]]:
        """分析单个克制关系
        
        Args:
            hero_id: 英雄 ID
            enemy_id: 敌方英雄 ID
            
        Returns:
            (score, reasons): 得分和理由列表
        """
        matchup_data = self.client.get_hero_matchups(hero_id)
        if not matchup_data:
            return 0.0, []
        
        # 查找对应的克制数据
        for matchup in matchup_data:
            if matchup.get("hero_id") == enemy_id:
                # 应用所有评分策略
                total_score = 0.0
                all_reasons = []
                
                for strategy in self._strategies:
                    score, reasons = strategy.calculate(matchup, self.config)
                    total_score += score
                    all_reasons.extend(reasons)
                
                return total_score, all_reasons
        
        return 0.0, []
    
    def _calculate_synergy(
        self,
        hero_id: int,
        ally_id: int
    ) -> Tuple[float, List[str]]:
        """计算英雄配合得分
        
        Args:
            hero_id: 英雄 ID
            ally_id: 友方英雄 ID
            
        Returns:
            (score, reasons): 得分和理由列表
        """
        # TODO: 未来可以查询同队胜率数据
        # 目前简化处理，不给额外分数
        return 0.0, []
    
    def analyze_matchups(
        self,
        our_heroes: List[str],
        enemy_heroes: List[str],
        top_n: int = 3
    ) -> List[Dict[str, Any]]:
        """分析英雄克制关系，推荐英雄
        
        Args:
            our_heroes: 己方已选英雄名称列表
            enemy_heroes: 对方已选英雄名称列表
            top_n: 返回推荐英雄数量
            
        Returns:
            List[Dict]: 推荐英雄列表，包含英雄名称、理由、胜率等
        """
        # 获取所有英雄
        all_heroes = self.client.get_heroes()
        if not all_heroes:
            return []
        
        # 转换英雄名称为 ID
        our_hero_ids = self._hero_names_to_ids(our_heroes)
        enemy_hero_ids = self._hero_names_to_ids(enemy_heroes)
        
        # 计算每个候选英雄的得分
        candidate_scores: List[Dict[str, Any]] = []
        
        for hero in all_heroes:
            hero_result = self._evaluate_hero(hero, our_hero_ids, enemy_hero_ids)
            if hero_result:
                candidate_scores.append(hero_result)
        
        # 按得分排序，返回前 N 个
        candidate_scores.sort(key=lambda x: x["score"], reverse=True)
        return candidate_scores[:top_n]
    
    def _evaluate_hero(
        self,
        hero: Dict[str, Any],
        our_hero_ids: List[int],
        enemy_hero_ids: List[int]
    ) -> Optional[Dict[str, Any]]:
        """评估单个英雄
        
        Args:
            hero: 英雄数据
            our_hero_ids: 己方英雄 ID 列表
            enemy_hero_ids: 敌方英雄 ID 列表
            
        Returns:
            评估结果，如果不满足条件返回 None
        """
        hero_id = hero["id"]
        hero_name = hero.get("localized_name", "")
        
        # 跳过已选英雄
        if hero_id in our_hero_ids or hero_id in enemy_hero_ids:
            return None
        
        total_score = 0.0
        all_reasons: List[str] = []
        matchup_details: List[Dict[str, Any]] = []
        
        # 1. 分析对敌方英雄的克制（加分）
        for enemy_id in enemy_hero_ids:
            score, reasons = self._analyze_single_matchup(hero_id, enemy_id)
            if score > 0:
                enemy_name = self.client.hero_id_to_name(enemy_id)
                total_score += score
                for reason in reasons:
                    all_reasons.append(f"对 {enemy_name}: {reason}")
                matchup_details.append({
                    "enemy_hero": enemy_name,
                    "advantage": score,
                    "reasons": reasons,
                })
        
        # 2. 分析与己方英雄的配合（加分）
        for ally_id in our_hero_ids:
            synergy_score, synergy_reasons = self._calculate_synergy(hero_id, ally_id)
            if synergy_score > 0:
                ally_name = self.client.hero_id_to_name(ally_id)
                total_score += synergy_score
                all_reasons.extend(synergy_reasons)
        
        # 只返回有正收益的英雄
        if total_score <= 0:
            return None
        
        return {
            "hero_id": hero_id,
            "hero_name": hero_name,
            "score": round(total_score, 2),
            "reasons": all_reasons,
            "matchup_details": matchup_details,
        }
    
    def _hero_names_to_ids(self, hero_names: List[str]) -> List[int]:
        """将英雄名称列表转换为 ID 列表
        
        Args:
            hero_names: 英雄名称列表
            
        Returns:
            英雄 ID 列表（过滤掉 None）
        """
        hero_ids = [self.client.hero_name_to_id(name) for name in hero_names]
        return [hid for hid in hero_ids if hid is not None]
    
    def get_counter_heroes(
        self,
        target_hero: str,
        top_n: int = 5
    ) -> List[Dict[str, Any]]:
        """获取克制特定英雄的英雄列表
        
        Args:
            target_hero: 目标英雄名称
            top_n: 返回数量
            
        Returns:
            List[Dict]: 克制该英雄的英雄列表
        """
        target_id = self.client.hero_name_to_id(target_hero)
        if not target_id:
            return []
        
        all_heroes = self.client.get_heroes()
        if not all_heroes:
            return []
        
        counters = []
        
        for hero in all_heroes:
            hero_id = hero["id"]
            if hero_id == target_id:
                continue
            
            score, reasons = self._analyze_single_matchup(hero_id, target_id)
            if score > 0:
                counters.append({
                    "hero_id": hero_id,
                    "hero_name": hero.get("localized_name", ""),
                    "score": round(score, 2),
                    "reasons": reasons,
                })
        
        # 按得分排序
        counters.sort(key=lambda x: x["score"], reverse=True)
        return counters[:top_n]
    
    def analyze_team_composition(
        self,
        our_heroes: List[str],
        enemy_heroes: List[str]
    ) -> Dict[str, Any]:
        """分析双方阵容
        
        Args:
            our_heroes: 己方英雄列表
            enemy_heroes: 敌方英雄列表
            
        Returns:
            阵容分析结果
        """
        our_hero_ids = self._hero_names_to_ids(our_heroes)
        enemy_hero_ids = self._hero_names_to_ids(enemy_heroes)
        
        # 分析己方优势
        our_advantages = []
        for hero_id in our_hero_ids:
            for enemy_id in enemy_hero_ids:
                score, reasons = self._analyze_single_matchup(hero_id, enemy_id)
                if score > 0:
                    our_advantages.append({
                        "hero": self.client.hero_id_to_name(hero_id),
                        "against": self.client.hero_id_to_name(enemy_id),
                        "score": round(score, 2),
                    })
        
        # 分析敌方优势
        enemy_advantages = []
        for enemy_id in enemy_hero_ids:
            for hero_id in our_hero_ids:
                score, reasons = self._analyze_single_matchup(enemy_id, hero_id)
                if score > 0:
                    enemy_advantages.append({
                        "hero": self.client.hero_id_to_name(enemy_id),
                        "against": self.client.hero_id_to_name(hero_id),
                        "score": round(score, 2),
                    })
        
        # 计算总体优势
        total_our_score = sum(adv["score"] for adv in our_advantages)
        total_enemy_score = sum(adv["score"] for adv in enemy_advantages)
        overall_advantage = total_our_score - total_enemy_score
        
        return {
            "our_advantages": our_advantages,
            "enemy_advantages": enemy_advantages,
            "overall_advantage": round(overall_advantage, 2),
            "conclusion": self._generate_conclusion(overall_advantage),
        }
    
    def _generate_conclusion(self, advantage: float) -> str:
        """生成结论
        
        Args:
            advantage: 优势分数
            
        Returns:
            结论文本
        """
        if advantage > 10:
            return "阵容优势较大"
        elif advantage > 0:
            return "阵容略有优势"
        elif advantage > -10:
            return "阵容势均力敌"
        else:
            return "阵容处于劣势"
