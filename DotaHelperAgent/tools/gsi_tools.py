"""GSI Agent 工具 - 提供 Agent 可调用的 GSI 数据访问接口"""

from typing import Dict, Any, List

from tools.base import Tool
from utils.log_config import get_logger

logger = get_logger("gsi_tools", component="tools")


class GSIDataTool(Tool):
    """获取当前游戏实时状态"""

    def __init__(self, state_manager):
        self.state_manager = state_manager
        super().__init__(
            name="get_gsi_state",
            description="获取当前游戏的实时状态数据，包括英雄信息、金钱、血量、技能冷却、物品栏等。仅在游戏进行中可用。",
            parameters={},
            func=self._get_state,
            category="gsi",
            examples=["当前游戏状态怎么样", "我的英雄现在有多少钱"],
        )

    def _get_state(self) -> Dict[str, Any]:
        state = self.state_manager.get_state()
        if not state:
            return {"available": False, "message": "当前未检测到游戏状态，可能不在游戏中或 GSI 未连接"}
        return {
            "available": True,
            "hero": state.hero_name,
            "level": state.level,
            "alive": state.alive,
            "health": f"{state.health}/{state.max_health}",
            "mana": f"{state.mana}/{state.max_mana}",
            "gold": state.gold,
            "kills": state.kills,
            "deaths": state.deaths,
            "assists": state.assists,
            "gpm": state.gpm,
            "xpm": state.xpm,
            "game_time": state.game_time,
            "game_state": state.game_state,
            "inventory": [item.name for item in state.inventory],
        }


class GSIRecentEventsTool(Tool):
    """获取最近的 GSI 事件"""

    def __init__(self, event_queue):
        self.event_queue = event_queue
        super().__init__(
            name="get_gsi_events",
            description="获取最近的游戏事件列表，如堆野提醒、符文刷新、击杀/死亡等事件。",
            parameters={"count": int},
            func=self._get_events,
            category="gsi",
            examples=["最近有什么游戏事件"],
        )

    def _get_events(self, count: int = 10) -> Dict[str, Any]:
        events = self.event_queue.get_recent(count)
        return {
            "count": len(events),
            "events": [{"type": e.event_type, "message": e.message, "priority": e.priority} for e in events],
        }


def create_gsi_tools(state_manager=None, event_queue=None) -> List[Tool]:
    """创建 GSI 相关的 Agent Tools"""
    tools = []
    if state_manager:
        tools.append(GSIDataTool(state_manager))
    if event_queue:
        tools.append(GSIRecentEventsTool(event_queue))
    return tools
