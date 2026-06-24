"""
决策融合器 - 多源决策融合 + 冲突解决

职责：
- 并行调用规则引擎、数据引擎、LLM 引擎
- 融合多个决策源的推荐结果
- 检测并解决决策冲突
- 输出最终推荐

融合策略：
- 加权平均（weighted_average）：按权重融合所有推荐
- 最高置信度（max_confidence）：选择置信度最高的推荐
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
import logging

from core.decision.rule_engine import RuleEngine
from core.decision.data_engine import DataEngine
from core.decision.llm_engine import LLMEngine

logger = logging.getLogger(__name__)


class ConflictResolution(Enum):
    """冲突解决策略"""
    WEIGHTED_AVERAGE = "weighted_average"  # 加权平均
    MAX_CONFIDENCE = "max_confidence"      # 最高置信度


@dataclass
class FusedRecommendation:
    """融合后的推荐结果"""
    recommendation: str
    confidence: float
    sources: List[str]
    all_recommendations: List[Dict[str, Any]]
    conflict_detected: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "sources": self.sources,
            "all_recommendations": self.all_recommendations,
            "conflict_detected": self.conflict_detected
        }


class DecisionFusion:
    """决策融合器"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化决策融合器
        
        Args:
            config: 配置字典
        """
        self.config = config or {}
        
        # 初始化三个决策引擎
        self.rule_engine = RuleEngine(config.get("rule_engine", {}))
        self.data_engine = DataEngine(config.get("data_engine", {}))
        self.llm_engine = LLMEngine(config.get("llm_engine", {}))
        
        # 融合配置
        self.conflict_resolution = ConflictResolution(
            self.config.get("conflict_resolution", "weighted_average")
        )
        self.min_confidence = self.config.get("min_confidence", 0.5)
        
        logger.info(f"决策融合器初始化完成，冲突解决策略: {self.conflict_resolution.value}")
    
    def set_data_engine_dependencies(self, api_client=None, cache=None):
        """
        设置数据引擎依赖
        
        Args:
            api_client: API 客户端
            cache: 缓存实例
        """
        if api_client:
            self.data_engine.set_api_client(api_client)
        if cache:
            self.data_engine.set_cache(cache)
    
    def set_llm_engine_dependencies(self, llm_client=None, knowledge_system=None):
        """
        设置 LLM 引擎依赖
        
        Args:
            llm_client: LLM 客户端
            knowledge_system: 知识库系统
        """
        if llm_client:
            self.llm_engine.set_llm_client(llm_client)
        if knowledge_system:
            self.llm_engine.set_knowledge_system(knowledge_system)
    
    def generate_recommendation(
        self,
        event: Any,  # GSIEvent object
        game_state: Any  # GameState object or dict
    ) -> Optional[FusedRecommendation]:
        """
        生成融合推荐
        
        Args:
            event: GSI 事件对象
            game_state: 游戏状态（GameState 对象或字典）
        
        Returns:
            融合后的推荐结果，如果无推荐返回 None
        """
        # 归一化 game_state 为字典
        game_state_dict = self._normalize_game_state(game_state)
        
        # 提取事件类型
        event_type = event.event_type if hasattr(event, 'event_type') else str(event)
        
        all_recommendations = []
        
        # 1. 调用规则引擎
        rule_results = self._call_rule_engine(event, game_state)
        if rule_results:
            all_recommendations.extend(rule_results)
        
        # 2. 调用数据引擎
        data_result = self._call_data_engine(event, game_state)
        if data_result:
            all_recommendations.append(data_result)
        
        # 3. 调用 LLM 引擎
        llm_result = self._call_llm_engine(event, game_state)
        if llm_result:
            all_recommendations.append(llm_result)
        
        if not all_recommendations:
            logger.info("所有引擎均未产生推荐")
            return None
        
        # 4. 融合推荐
        fused = self._fuse_recommendations(all_recommendations)
        
        # 5. 置信度过滤
        if fused.confidence < self.min_confidence:
            logger.info(f"融合推荐置信度 {fused.confidence:.2f} 低于阈值 {self.min_confidence}")
            return None
        
        return fused
    
    def _normalize_game_state(self, game_state: Any) -> Dict[str, Any]:
        """
        将游戏状态归一化为字典
        
        Args:
            game_state: GameState 对象或字典
        
        Returns:
            归一化后的字典
        """
        if game_state is None:
            return {}
        
        if isinstance(game_state, dict):
            return game_state
        
        # GameState 对象，转换为字典
        if hasattr(game_state, 'to_dict'):
            state_dict = game_state.to_dict()
            # 添加一些别名以兼容规则引擎
            state_dict['is_alive'] = state_dict.get('alive', True)
            state_dict['health_percent'] = (
                state_dict.get('health', 0) / state_dict.get('max_health', 1)
                if state_dict.get('max_health', 0) > 0 else 0
            )
            state_dict['mana_percent'] = (
                state_dict.get('mana', 0) / state_dict.get('max_mana', 1)
                if state_dict.get('max_mana', 0) > 0 else 0
            )
            return state_dict
        
        return {}
    
    def _call_rule_engine(self, event: Any, game_state: Any) -> List[Dict[str, Any]]:
        """
        调用规则引擎
        
        Args:
            event: GSI 事件
            game_state: 游戏状态
        
        Returns:
            推荐列表
        """
        try:
            recommendations = self.rule_engine.get_recommendations(event, game_state)
            return recommendations
        except Exception as e:
            logger.error(f"调用规则引擎失败: {e}")
            return []
    
    def _call_data_engine(self, event: Any, game_state: Any) -> Optional[Dict[str, Any]]:
        """
        调用数据引擎
        
        Args:
            event: GSI 事件
            game_state: 游戏状态
        
        Returns:
            推荐结果
        """
        try:
            result = self.data_engine.generate_recommendation(event, game_state)
            if result:
                return result.to_dict()
            return None
        except Exception as e:
            logger.error(f"调用数据引擎失败: {e}")
            return None
    
    def _call_llm_engine(self, event: Any, game_state: Any) -> Optional[Dict[str, Any]]:
        """
        调用 LLM 引擎
        
        Args:
            event: GSI 事件
            game_state: 游戏状态
        
        Returns:
            推荐结果
        """
        try:
            result = self.llm_engine.generate_recommendation(event, game_state)
            if result:
                return result.to_dict()
            return None
        except Exception as e:
            logger.error(f"调用 LLM 引擎失败: {e}")
            return None
    
    def _fuse_recommendations(
        self,
        recommendations: List[Dict[str, Any]]
    ) -> FusedRecommendation:
        """
        融合推荐结果
        
        Args:
            recommendations: 推荐列表
        
        Returns:
            融合后的推荐
        """
        # 检测冲突
        conflict_detected = self._detect_conflict(recommendations)
        
        if conflict_detected:
            # 解决冲突
            return self._resolve_conflict(recommendations)
        
        # 无冲突，按策略融合
        if self.conflict_resolution == ConflictResolution.MAX_CONFIDENCE:
            return self._fuse_by_max_confidence(recommendations)
        else:
            return self._fuse_by_weighted_average(recommendations)
    
    def _detect_conflict(self, recommendations: List[Dict[str, Any]]) -> bool:
        """
        检测决策冲突
        
        Args:
            recommendations: 推荐列表
        
        Returns:
            是否存在冲突
        """
        if len(recommendations) < 2:
            return False
        
        # 提取所有推荐内容
        rec_texts = [r.get("recommendation", "") for r in recommendations]
        
        # 简单冲突检测：检查是否有明显矛盾的关键词
        conflict_keywords = {
            "激进": ["保守", "撤退", "回城"],
            "保守": ["激进", "进攻", "击杀"],
            "回城": ["进攻", "击杀", "激进"],
            "进攻": ["撤退", "回城", "保守"]
        }
        
        for rec_text in rec_texts:
            for keyword, conflicts in conflict_keywords.items():
                if keyword in rec_text:
                    for other_text in rec_texts:
                        if other_text != rec_text:
                            if any(conflict in other_text for conflict in conflicts):
                                logger.info(f"检测到决策冲突: '{keyword}' vs 冲突词")
                                return True
        
        return False
    
    def _resolve_conflict(
        self,
        recommendations: List[Dict[str, Any]]
    ) -> FusedRecommendation:
        """
        解决决策冲突
        
        Args:
            recommendations: 推荐列表
        
        Returns:
            解决冲突后的推荐
        """
        logger.info("开始解决决策冲突")
        
        # 使用最高置信度策略解决冲突
        return self._fuse_by_max_confidence(recommendations)
    
    def _fuse_by_max_confidence(
        self,
        recommendations: List[Dict[str, Any]]
    ) -> FusedRecommendation:
        """
        按最高置信度融合
        
        Args:
            recommendations: 推荐列表
        
        Returns:
            融合后的推荐
        """
        # 找到置信度最高的推荐
        best_rec = max(recommendations, key=lambda r: r.get("confidence", 0))
        
        return FusedRecommendation(
            recommendation=best_rec.get("recommendation", ""),
            confidence=best_rec.get("confidence", 0),
            sources=[best_rec.get("engine", "unknown")],
            all_recommendations=recommendations,
            conflict_detected=True
        )
    
    def _fuse_by_weighted_average(
        self,
        recommendations: List[Dict[str, Any]]
    ) -> FusedRecommendation:
        """
        按加权平均融合
        
        Args:
            recommendations: 推荐列表
        
        Returns:
            融合后的推荐
        """
        # 定义引擎权重
        engine_weights = {
            "rule": 0.3,
            "data": 0.4,
            "llm": 0.3
        }
        
        # 计算加权置信度
        total_weight = 0
        weighted_confidence = 0
        
        for rec in recommendations:
            engine = rec.get("engine", "unknown")
            weight = engine_weights.get(engine, 0.1)
            confidence = rec.get("confidence", 0)
            
            total_weight += weight
            weighted_confidence += weight * confidence
        
        if total_weight > 0:
            final_confidence = weighted_confidence / total_weight
        else:
            final_confidence = 0
        
        # 选择置信度最高的推荐作为最终推荐
        best_rec = max(recommendations, key=lambda r: r.get("confidence", 0))
        
        # 收集所有来源
        sources = list(set(r.get("engine", "unknown") for r in recommendations))
        
        return FusedRecommendation(
            recommendation=best_rec.get("recommendation", ""),
            confidence=final_confidence,
            sources=sources,
            all_recommendations=recommendations,
            conflict_detected=False
        )
