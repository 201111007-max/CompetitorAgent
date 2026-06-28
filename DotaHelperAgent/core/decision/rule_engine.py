"""
规则推理引擎 - 基于领域专家规则快速推荐

职责：
- 基于 Dota 2 领域知识定义规则
- 快速响应游戏事件（延迟 < 10ms）
- 提供可解释的推荐建议

规则类型：
- 血量预警规则
- 出装推荐规则
- 时机把握规则
- 对线策略规则
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class RulePriority(Enum):
    """规则优先级"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Rule:
    """规则定义"""
    id: str
    name: str
    description: str
    priority: RulePriority
    condition: str  # 条件表达式（字符串形式，便于序列化）
    recommendation: str
    confidence: float
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "priority": self.priority.value,
            "condition": self.condition,
            "recommendation": self.recommendation,
            "confidence": self.confidence
        }


@dataclass
class RuleResult:
    """规则匹配结果"""
    rule: Rule
    matched: bool
    context: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "rule": self.rule.to_dict(),
            "matched": self.matched,
            "context": self.context
        }


class RuleEngine:
    """规则推理引擎"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None, strategy_params=None):
        """
        初始化规则引擎
        
        Args:
            config: 配置字典
            strategy_params: 策略参数管理实例（可选，用于动态规则参数）
        """
        self.config = config or {}
        self.strategy_params = strategy_params
        self.rules: List[Rule] = []
        self._load_default_rules()
        logger.info(f"规则引擎初始化完成，加载 {len(self.rules)} 条规则")
    
    def _load_default_rules(self):
        """加载默认规则"""
        # 从策略参数读取动态阈值（如有）
        low_health_threshold = 0.3
        if self.strategy_params:
            low_health_threshold = self.strategy_params.get_rule_param(
                "low_health_threshold", default=0.3
            )

        # 血量预警规则
        self.rules.append(Rule(
            id="health_warning",
            name="血量预警",
            description="当英雄血量低于阈值时发出预警",
            priority=RulePriority.HIGH,
            condition=f"health_percent < {low_health_threshold}",
            recommendation="血量较低，建议回城补给或购买治疗道具",
            confidence=0.9
        ))
        
        # 魔法预警规则
        self.rules.append(Rule(
            id="mana_warning",
            name="魔法预警",
            description="当英雄魔法低于阈值时发出预警",
            priority=RulePriority.MEDIUM,
            condition="mana_percent < 0.2",
            recommendation="魔法不足，建议购买魔法药水或回城补给",
            confidence=0.85
        ))
        
        # 堆野时机规则
        self.rules.append(Rule(
            id="stack_neutral",
            name="堆野时机",
            description="在合适的时机提示堆野",
            priority=RulePriority.MEDIUM,
            condition="game_time % 60 >= 53 and game_time % 60 <= 55",
            recommendation="可以堆野了！拉野怪让中立生物堆积",
            confidence=0.8
        ))
        
        # 符文刷新规则
        self.rules.append(Rule(
            id="rune_spawn",
            name="符文刷新",
            description="提示符文刷新时机",
            priority=RulePriority.MEDIUM,
            condition="game_time % 180 == 0",
            recommendation="符文即将刷新，可以控符",
            confidence=0.75
        ))
        
        # 肉山刷新规则
        self.rules.append(Rule(
            id="roshan_respawn",
            name="肉山刷新",
            description="提示肉山可能刷新",
            priority=RulePriority.HIGH,
            condition="game_time >= 480 and game_time % 480 == 0",
            recommendation="肉山可能已刷新，可以考虑击杀获取不朽之守护",
            confidence=0.7
        ))
        
        # 出装推荐规则 - 早期
        self.rules.append(Rule(
            id="early_item_recommendation",
            name="早期出装推荐",
            description="游戏早期推荐基础出装",
            priority=RulePriority.LOW,
            condition="game_time < 600",
            recommendation="建议优先购买基础属性装和恢复道具",
            confidence=0.6
        ))
        
        # 出装推荐规则 - 中期
        self.rules.append(Rule(
            id="mid_item_recommendation",
            name="中期出装推荐",
            description="游戏中期推荐核心装备",
            priority=RulePriority.MEDIUM,
            condition="600 <= game_time < 1200",
            recommendation="建议开始合成核心装备，提升战斗力",
            confidence=0.65
        ))
        
        # 出装推荐规则 - 后期
        self.rules.append(Rule(
            id="late_item_recommendation",
            name="后期出装推荐",
            description="游戏后期推荐神装",
            priority=RulePriority.MEDIUM,
            condition="game_time >= 1200",
            recommendation="建议完善神装，考虑购买圣剑等终极装备",
            confidence=0.6
        ))
        
        # 死亡预警规则
        self.rules.append(Rule(
            id="death_warning",
            name="死亡预警",
            description="当英雄即将死亡时发出预警",
            priority=RulePriority.CRITICAL,
            condition="health_percent < 0.1 and is_alive",
            recommendation="危险！血量极低，立即撤退或使用逃生技能",
            confidence=0.95
        ))
        
        # 买活建议规则
        self.rules.append(Rule(
            id="buyback_suggestion",
            name="买活建议",
            description="在关键时刻建议买活",
            priority=RulePriority.HIGH,
            condition="not is_alive and game_time > 1200 and gold >= buyback_cost",
            recommendation="建议买活参与关键团战",
            confidence=0.8
        ))
    
    def evaluate(self, game_state: Any) -> List[RuleResult]:
        """
        评估游戏状态，返回匹配的规则结果
        
        Args:
            game_state: 游戏状态（GameState 对象或字典）
        
        Returns:
            匹配的规则结果列表
        """
        state_dict = self._normalize_game_state(game_state)
        results = []
        
        for rule in self.rules:
            try:
                # 评估规则条件
                matched = self._evaluate_condition(rule.condition, state_dict)
                
                if matched:
                    result = RuleResult(
                        rule=rule,
                        matched=True,
                        context=state_dict
                    )
                    results.append(result)
                    logger.debug(f"规则 {rule.name} 匹配")
            
            except Exception as e:
                logger.error(f"评估规则 {rule.id} 时出错: {e}")
                continue
        
        # 按优先级排序
        results.sort(key=lambda r: r.rule.priority.value, reverse=True)
        
        return results
    
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
            state_dict = game_state.copy()
        elif hasattr(game_state, 'to_dict'):
            state_dict = game_state.to_dict()
        else:
            return {}
        
        # 添加别名以兼容规则条件表达式
        state_dict.setdefault('is_alive', state_dict.get('alive', True))
        
        # 计算派生属性
        max_health = state_dict.get('max_health', 0)
        health = state_dict.get('health', 0)
        state_dict.setdefault('health_percent',
            health / max_health if max_health > 0 else 1.0)
        
        max_mana = state_dict.get('max_mana', 0)
        mana = state_dict.get('mana', 0)
        state_dict.setdefault('mana_percent',
            mana / max_mana if max_mana > 0 else 1.0)
        
        return state_dict
    
    def _evaluate_condition(self, condition: str, game_state: Dict[str, Any]) -> bool:
        """
        评估条件表达式
        
        Args:
            condition: 条件表达式字符串
            game_state: 游戏状态字典
        
        Returns:
            条件是否满足
        """
        try:
            # 将游戏状态作为局部变量，提供安全默认值
            local_vars = {
                'health_percent': 1.0,
                'mana_percent': 1.0,
                'game_time': 0,
                'is_alive': True,
                'gold': 0,
                'buyback_cost': 999999,
                'level': 1,
            }
            local_vars.update(game_state)
            
            # 评估表达式
            result = eval(condition, {"__builtins__": {}}, local_vars)
            return bool(result)
        
        except Exception as e:
            logger.debug(f"条件评估失败: {condition}, 错误: {e}")
            return False
    
    def get_recommendations(self, event: Any, game_state: Any = None) -> List[Dict[str, Any]]:
        """
        获取推荐建议
        
        Args:
            event: GSI 事件对象
            game_state: 游戏状态（GameState 对象或字典）
        
        Returns:
            推荐建议列表
        """
        # 归一化游戏状态
        state_dict = self._normalize_game_state(game_state)
        results = self.evaluate(state_dict)
        
        recommendations = []
        for result in results:
            if result.matched:
                recommendations.append({
                    "engine": "rule",
                    "type": "rule",
                    "rule_id": result.rule.id,
                    "rule_name": result.rule.name,
                    "priority": result.rule.priority.name,
                    "recommendation": result.rule.recommendation,
                    "confidence": result.rule.confidence,
                    "context": result.context
                })
        
        return recommendations
    
    def add_rule(self, rule: Rule):
        """
        添加自定义规则
        
        Args:
            rule: 规则对象
        """
        self.rules.append(rule)
        logger.info(f"添加规则: {rule.name}")
    
    def remove_rule(self, rule_id: str) -> bool:
        """
        移除规则
        
        Args:
            rule_id: 规则 ID
        
        Returns:
            是否成功移除
        """
        for i, rule in enumerate(self.rules):
            if rule.id == rule_id:
                self.rules.pop(i)
                logger.info(f"移除规则: {rule_id}")
                return True
        return False
    
    def get_all_rules(self) -> List[Dict[str, Any]]:
        """
        获取所有规则
        
        Returns:
            规则字典列表
        """
        return [rule.to_dict() for rule in self.rules]
