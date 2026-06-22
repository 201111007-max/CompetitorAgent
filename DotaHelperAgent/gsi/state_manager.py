"""GSI 状态管理器 - 状态缓存、变化检测、事件触发"""

import threading
from typing import Optional, Dict, Any

from gsi.models import GameState, parse_gsi_data
from utils.log_config import get_logger

logger = get_logger("gsi_state_manager", component="gsi")


class GSIStateManager:
    """GSI 状态管理器"""

    def __init__(self, event_handler=None):
        self.current_state: Optional[GameState] = None
        self.previous_state: Optional[GameState] = None
        self.event_handler = event_handler
        self._lock = threading.Lock()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def update_state(self, gsi_data: Dict[str, Any]) -> GameState:
        """更新游戏状态，检测变化并触发事件"""
        new_state = parse_gsi_data(gsi_data)

        with self._lock:
            self.previous_state = self.current_state
            self.current_state = new_state
            self._connected = True

        # 事件检测（仅在已有前一状态时触发）
        if self.previous_state is not None and self.event_handler is not None:
            self._detect_changes(self.previous_state, self.current_state)

        logger.debug(f"GSI 状态更新: hero={new_state.hero_name}, time={new_state.game_time}")
        return new_state

    def get_state(self) -> Optional[GameState]:
        """获取当前游戏状态"""
        with self._lock:
            return self.current_state

    def _detect_changes(self, prev: GameState, curr: GameState) -> None:
        """检测状态变化并触发事件"""
        handler = self.event_handler

        # 游戏状态变化
        if curr.game_state != prev.game_state:
            handler.on_game_state_changed(prev.game_state, curr.game_state)

        # 游戏时间 tick
        if curr.game_time != prev.game_time:
            handler.on_game_time_tick(curr, prev)

        # 击杀
        if curr.kills > prev.kills:
            handler.on_kill(curr)

        # 死亡
        if curr.alive != prev.alive and not curr.alive:
            handler.on_death(curr)

        # 金钱花费
        if curr.gold < prev.gold:
            spent = prev.gold - curr.gold
            gold_spent_cfg = getattr(handler, 'config', {}).get("gold_spent", {})
            threshold = gold_spent_cfg.get("threshold", 500)
            if spent >= threshold:
                handler.on_gold_spent(curr, spent)

        # 昼夜变化
        if curr.daytime != prev.daytime:
            handler.on_daytime_changed(curr)

        # 升级
        if curr.level > prev.level:
            handler.on_level_up(curr)
