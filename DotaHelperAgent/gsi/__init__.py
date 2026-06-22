"""GSI (Game State Integration) 模块

提供 Dota 2 游戏状态集成功能：
- GSI HTTP 服务器（接收游戏客户端推送）
- 游戏状态管理（缓存、变化检测）
- 事件处理（堆野、符文、昼夜等提醒）
- 事件队列（SSE 推送 + Agent 查询）
"""

__all__ = [
    'GameState',
    'AbilityInfo',
    'ItemInfo',
    'GSIEvent',
    'GSIStateManager',
    'GSIEventHandler',
    'GSIEventQueue',
    'GSIServer',
]


def __getattr__(name):
    """延迟导入模块"""
    if name == 'GameState':
        from .models import GameState
        return GameState
    elif name == 'AbilityInfo':
        from .models import AbilityInfo
        return AbilityInfo
    elif name == 'ItemInfo':
        from .models import ItemInfo
        return ItemInfo
    elif name == 'GSIEvent':
        from .models import GSIEvent
        return GSIEvent
    elif name == 'GSIStateManager':
        from .state_manager import GSIStateManager
        return GSIStateManager
    elif name == 'GSIEventHandler':
        from .event_handler import GSIEventHandler
        return GSIEventHandler
    elif name == 'GSIEventQueue':
        from .event_queue import GSIEventQueue
        return GSIEventQueue
    elif name == 'GSIServer':
        from .server import GSIServer
        return GSIServer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
