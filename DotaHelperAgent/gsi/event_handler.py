"""GSI 事件处理器 - 游戏事件检测与提醒生成"""

from typing import Dict, Any, Optional

from gsi.models import GameState, GSIEvent
from gsi.event_queue import GSIEventQueue
from utils.log_config import get_logger
from utils.voice_player import VoicePlayer

logger = get_logger("gsi_event_handler", component="gsi")


class GSIEventHandler:
    """GSI 事件处理器"""

    def __init__(
        self,
        event_queue: GSIEventQueue,
        config: Dict[str, Any] = None,
        voice_player: Optional[VoicePlayer] = None,
    ):
        self.event_queue = event_queue
        self.config = config or {}
        self.voice_player = voice_player
        self._last_stack_reminder_time: int = -60
        self._last_rune_reminder_time: int = -60

    def on_game_time_tick(self, state: GameState, prev: GameState) -> None:
        """游戏时间 tick — 检测定时事件"""
        t = state.game_time

        # 堆野提醒
        stack_cfg = self.config.get("stack", {})
        if stack_cfg.get("enabled", True):
            offset = stack_cfg.get("offset", 53)
            min_interval = stack_cfg.get("min_interval", 30)
            if t % 60 == offset and t - self._last_stack_reminder_time > min_interval:
                self._emit("stack", f"堆野时间到了！（游戏 {self._fmt_time(t)}）", "info")
                self._last_stack_reminder_time = t

        # 中符提醒
        mid_rune_cfg = self.config.get("mid_rune", {})
        if mid_rune_cfg.get("enabled", True):
            interval = mid_rune_cfg.get("interval", 120)
            if t > 0 and t % interval == 0 and t - self._last_rune_reminder_time > 60:
                self._emit("rune_mid", "中符刷新了！", "info")
                self._last_rune_reminder_time = t

        # 财神符提醒
        bounty_cfg = self.config.get("bounty_rune", {})
        if bounty_cfg.get("enabled", True):
            interval = bounty_cfg.get("interval", 180)
            if t > 0 and t % interval == 0:
                self._emit("rune_bounty", "财神符刷新了！", "info")

        # 智慧符提醒
        wisdom_cfg = self.config.get("wisdom_rune", {})
        if wisdom_cfg.get("enabled", True):
            interval = wisdom_cfg.get("interval", 420)
            if t > 0 and t % interval == 0:
                self._emit("rune_wisdom", "智慧符刷新了！", "info")

        # 莲花提醒
        lotus_cfg = self.config.get("lotus", {})
        if lotus_cfg.get("enabled", True):
            interval = lotus_cfg.get("interval", 180)
            if t > 0 and t % interval == 0:
                self._emit("rune_lotus", "莲花刷新了！", "info")

        # 中立物品提醒
        neutral_cfg = self.config.get("neutral_item", {})
        if neutral_cfg.get("enabled", True):
            interval = neutral_cfg.get("interval", 420)
            if t > 0 and t % interval == 0:
                self._emit("neutral", "中立物品刷新了！", "info")

        # 肉山提醒
        roshan_cfg = self.config.get("roshan", {})
        if roshan_cfg.get("enabled", True):
            interval = roshan_cfg.get("interval", 480)
            if t > 0 and t % interval == 0:
                self._emit("roshan", "肉山可能已复活，注意查看！", "warning")

    def on_game_state_changed(self, old_state: str, new_state: str) -> None:
        if new_state == "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS":
            self._emit("game_start", "游戏开始！祝你好运！", "info")
        elif new_state == "DOTA_GAMERULES_STATE_POST_GAME":
            self._emit("game_end", "游戏结束", "info")

    def on_kill(self, state: GameState) -> None:
        self._emit("kill", f"击杀！当前 KDA: {state.kills}/{state.deaths}/{state.assists}", "info")

    def on_death(self, state: GameState) -> None:
        self._emit("death", f"阵亡！复活时间: {state.respawn_seconds}s", "warning")

    def on_gold_spent(self, state: GameState, amount: int) -> None:
        self._emit("item", f"购买了物品（花费 {amount} 金），剩余 {state.gold} 金", "info")

    def on_daytime_changed(self, state: GameState) -> None:
        if state.daytime:
            self._emit("daytime", "切换到白天", "info")
        else:
            self._emit("nighttime", "切换到夜晚", "info")

    def on_level_up(self, state: GameState) -> None:
        self._emit("level_up", f"升级到 {state.level} 级！", "info")

    def _emit(self, event_type: str, message: str, priority: str) -> None:
        """发射事件并触发语音播放"""
        # 触发语音播放
        if self.voice_player:
            self.voice_player.play(event_type)
        
        # 创建事件并入队
        event = GSIEvent(event_type=event_type, message=message, priority=priority)
        self.event_queue.put(event)
        logger.debug(f"GSI 事件: [{priority}] {event_type} - {message}")

    @staticmethod
    def _fmt_time(seconds: int) -> str:
        m, s = divmod(abs(seconds), 60)
        return f"{m}:{s:02d}"
