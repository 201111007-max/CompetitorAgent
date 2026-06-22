"""GSI 状态管理器测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from gsi.state_manager import GSIStateManager


class MockEventHandler:
    def __init__(self):
        self.events = []

    def on_game_state_changed(self, old, new):
        self.events.append(("game_state_changed", old, new))

    def on_game_time_tick(self, curr, prev):
        self.events.append(("game_time_tick", curr.game_time))

    def on_kill(self, state):
        self.events.append(("kill", state.kills))

    def on_death(self, state):
        self.events.append(("death", state.respawn_seconds))

    def on_gold_spent(self, state, amount):
        self.events.append(("gold_spent", amount))

    def on_daytime_changed(self, state):
        self.events.append(("daytime_changed", state.daytime))

    def on_level_up(self, state):
        self.events.append(("level_up", state.level))


class TestGSIStateManager:
    def test_initial_state(self):
        manager = GSIStateManager()
        assert manager.get_state() is None
        assert manager.connected is False

    def test_update_state(self):
        manager = GSIStateManager()
        manager.update_state({"hero": {"name": "npc_dota_hero_pudge", "level": 6}})
        state = manager.get_state()
        assert state is not None
        assert state.hero_name == "npc_dota_hero_pudge"

    def test_detect_kill(self):
        handler = MockEventHandler()
        manager = GSIStateManager(event_handler=handler)
        manager.update_state({"player": {"kills": 0}})
        manager.update_state({"player": {"kills": 1}})
        assert ("kill", 1) in handler.events

    def test_detect_death(self):
        handler = MockEventHandler()
        manager = GSIStateManager(event_handler=handler)
        manager.update_state({"hero": {"alive": True}})
        manager.update_state({"hero": {"alive": False, "respawn_seconds": 15}})
        assert ("death", 15) in handler.events

    def test_detect_gold_spent(self):
        handler = MockEventHandler()
        manager = GSIStateManager(event_handler=handler)
        manager.update_state({"player": {"gold": 3000}})
        manager.update_state({"player": {"gold": 2000}})
        assert ("gold_spent", 1000) in handler.events

    def test_detect_level_up(self):
        handler = MockEventHandler()
        manager = GSIStateManager(event_handler=handler)
        manager.update_state({"hero": {"level": 5}})
        manager.update_state({"hero": {"level": 6}})
        assert ("level_up", 6) in handler.events

    def test_no_event_on_first_update(self):
        handler = MockEventHandler()
        manager = GSIStateManager(event_handler=handler)
        manager.update_state({"hero": {"level": 6}})
        assert len(handler.events) == 0

    def test_gold_spent_threshold(self):
        handler = MockEventHandler()
        manager = GSIStateManager(event_handler=handler)
        manager.update_state({"player": {"gold": 3000}})
        manager.update_state({"player": {"gold": 2800}})
        assert not any(e[0] == "gold_spent" for e in handler.events)
