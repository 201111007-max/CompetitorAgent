"""推荐查询工具 - 提供主动推荐查询接口"""

from typing import Dict, Any, List, Optional
from tools.base import Tool
from gsi.models import GSIEvent
from utils.log_config import get_logger

logger = get_logger("recommendation_tools", component="tools")


class RecommendationQueryTool(Tool):
    """查询主动推荐"""

    def __init__(self, decision_fusion, state_manager=None, event_queue=None):
        """
        初始化推荐查询工具
        
        Args:
            decision_fusion: 决策融合器实例
            state_manager: GSI 状态管理器（可选）
            event_queue: GSI 事件队列（可选）
        """
        self.decision_fusion = decision_fusion
        self.state_manager = state_manager
        self.event_queue = event_queue
        
        super().__init__(
            name="get_recommendation",
            description="获取基于当前游戏局势的主动推荐建议，包括出装、策略、局势分析等。",
            parameters={},
            func=self._get_recommendation,
            category="recommendation",
            examples=[
                "给我一些游戏建议",
                "当前局势怎么样",
                "我应该出什么装备"
            ],
        )

    def _get_recommendation(self) -> Dict[str, Any]:
        """
        获取推荐建议（无需参数，从最近事件生成推荐）
        
        Returns:
            推荐结果字典
        """
        try:
            # 获取当前游戏状态
            game_state = None
            if self.state_manager:
                game_state = self.state_manager.get_state()
            
            if not game_state:
                return {
                    "available": False,
                    "message": "当前不在游戏中"
                }
            
            # 获取最近事件
            recent_events = []
            if self.event_queue:
                recent_events = self.event_queue.get_recent(5)
            
            if not recent_events:
                return {
                    "available": False,
                    "message": "暂无游戏事件"
                }
            
            # 使用最近一个事件生成推荐
            event = recent_events[-1]
            
            # 调用决策融合器生成推荐
            recommendation = self.decision_fusion.generate_recommendation(
                event=event,
                game_state=game_state
            )
            
            if not recommendation:
                return {
                    "available": False,
                    "message": "暂无推荐建议"
                }
            
            return {
                "available": True,
                "recommendation": recommendation.recommendation,
                "confidence": recommendation.confidence,
                "sources": recommendation.sources
            }
        
        except Exception as e:
            logger.error(f"获取推荐失败: {e}", exc_info=True)
            return {
                "available": False,
                "message": f"获取推荐时发生错误: {str(e)}"
            }


class RecommendationStatusTool(Tool):
    """查询推荐系统状态"""

    def __init__(self, event_trigger):
        """
        初始化推荐状态工具
        
        Args:
            event_trigger: 事件触发器实例
        """
        self.event_trigger = event_trigger
        
        super().__init__(
            name="get_recommendation_status",
            description="查询主动推荐系统的运行状态，包括是否启用、冷却时间等信息。",
            parameters={},
            func=self._get_status,
            category="recommendation",
            examples=["推荐系统状态怎么样"],
        )

    def _get_status(self) -> Dict[str, Any]:
        """获取推荐系统状态"""
        try:
            if not self.event_trigger:
                return {
                    "available": False,
                    "message": "事件触发器未初始化"
                }
            
            status = self.event_trigger.get_status()
            return {
                "available": True,
                "status": status
            }
        
        except Exception as e:
            logger.error(f"获取推荐状态失败: {e}", exc_info=True)
            return {
                "available": False,
                "message": f"获取状态时发生错误: {str(e)}"
            }


def create_recommendation_tools(
    decision_fusion,
    state_manager=None,
    event_trigger=None,
    event_queue=None
) -> List[Tool]:
    """
    创建推荐相关的 Agent Tools
    
    Args:
        decision_fusion: 决策融合器实例
        state_manager: GSI 状态管理器（可选）
        event_trigger: 事件触发器实例（可选）
        event_queue: GSI 事件队列（可选）
    
    Returns:
        工具列表
    """
    tools = []
    
    if decision_fusion:
        # 优先使用 event_trigger 中的 event_queue，否则使用传入的 event_queue
        eq = event_queue
        if event_trigger and hasattr(event_trigger, 'event_queue'):
            eq = event_trigger.event_queue
        tools.append(RecommendationQueryTool(decision_fusion, state_manager, event_queue=eq))
    
    if event_trigger:
        tools.append(RecommendationStatusTool(event_trigger))
    
    return tools
