"""GSI 事件处理器测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from gsi.models import GameState
from gsi.event_handler import GSIEventHandler
from gsi.event_queue import GSIEventQueue


class TestGSIEventHandler:
    def _make_state(self, game_time=0, **kwargs) -> GameState:
        return GameState(game_time=game_time, **kwargs)

    def test_stack_reminder(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq, {"stack": {"enabled": True, "offset": 53, "min_interval": 30}})
        handler.on_game_time_tick(self._make_state(game_time=53), self._make_state(game_time=52))
        events = eq.get_recent(1)
        assert len(events) == 1
        assert events[0].event_type == "stack"

    def test_stack_disabled(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq, {"stack": {"enabled": False}})
        handler.on_game_time_tick(self._make_state(game_time=53), self._make_state(game_time=52))
        assert len(eq.get_recent(1)) == 0

    def test_mid_rune(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq, {"mid_rune": {"enabled": True, "interval": 120}})
        handler.on_game_time_tick(self._make_state(game_time=120), self._make_state(game_time=119))
        events = eq.get_recent(1)
        assert events[0].event_type == "rune"
        assert "中符" in events[0].message

    def test_bounty_rune(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq, {"bounty_rune": {"enabled": True, "interval": 180}, "lotus": {"enabled": False}})
        handler.on_game_time_tick(self._make_state(game_time=180), self._make_state(game_time=179))
        assert "财神符" in eq.get_recent(1)[0].message

    def test_game_start(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq)
        handler.on_game_state_changed("", "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS")
        assert eq.get_recent(1)[0].event_type == "game_start"

    def test_game_end(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq)
        handler.on_game_state_changed("", "DOTA_GAMERULES_STATE_POST_GAME")
        assert eq.get_recent(1)[0].event_type == "game_end"

    def test_kill_event(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq)
        handler.on_kill(self._make_state(kills=5, deaths=2, assists=8))
        assert "5/2/8" in eq.get_recent(1)[0].message

    def test_death_event(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq)
        handler.on_death(self._make_state(respawn_seconds=15))
        assert eq.get_recent(1)[0].priority == "warning"

    def test_daytime_change(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq)
        handler.on_daytime_changed(self._make_state(daytime=False))
        assert "夜晚" in eq.get_recent(1)[0].message

    def test_level_up(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq)
        handler.on_level_up(self._make_state(level=6))
        assert "6" in eq.get_recent(1)[0].message

    def test_fmt_time(self):
        assert GSIEventHandler._fmt_time(0) == "0:00"
        assert GSIEventHandler._fmt_time(53) == "0:53"
        assert GSIEventHandler._fmt_time(120) == "2:00"
