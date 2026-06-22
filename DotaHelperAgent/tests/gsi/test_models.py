"""GSI 数据模型测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from gsi.models import GameState, AbilityInfo, ItemInfo, GSIEvent, parse_gsi_data


class TestAbilityInfo:
    def test_default_values(self):
        ability = AbilityInfo()
        assert ability.name == ""
        assert ability.level == 0

    def test_to_dict(self):
        ability = AbilityInfo(name="q", level=3, can_cast=True)
        d = ability.to_dict()
        assert d["name"] == "q"
        assert d["level"] == 3


class TestItemInfo:
    def test_default_values(self):
        item = ItemInfo()
        assert item.name == ""

    def test_to_dict(self):
        item = ItemInfo(name="blink", slot="slot0", charges=1)
        d = item.to_dict()
        assert d["name"] == "blink"
        assert d["slot"] == "slot0"


class TestGameState:
    def test_default_values(self):
        state = GameState()
        assert state.game_time == 0
        assert state.alive is True
        assert state.level == 1

    def test_to_dict(self):
        state = GameState(hero_name="npc_dota_hero_pudge", level=6, kills=3)
        d = state.to_dict()
        assert d["hero_name"] == "npc_dota_hero_pudge"
        assert d["level"] == 6


class TestGSIEvent:
    def test_default_values(self):
        event = GSIEvent(event_type="stack", message="堆野时间到了")
        assert event.priority == "info"

    def test_to_dict(self):
        event = GSIEvent(event_type="rune", message="中符刷新", priority="warning")
        d = event.to_dict()
        assert d["event_type"] == "rune"


class TestParseGSIData:
    def test_parse_empty(self):
        state = parse_gsi_data({})
        assert state.game_time == 0

    def test_parse_map(self):
        data = {"map": {"game_time": 600, "radiant_score": 10, "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"}}
        state = parse_gsi_data(data)
        assert state.game_time == 600
        assert state.radiant_score == 10

    def test_parse_hero(self):
        data = {"hero": {"name": "npc_dota_hero_pudge", "id": 14, "level": 6, "health": 800, "max_health": 1000}}
        state = parse_gsi_data(data)
        assert state.hero_name == "npc_dota_hero_pudge"
        assert state.health == 800

    def test_parse_player(self):
        data = {"player": {"name": "TestPlayer", "kills": 5, "gold": 3000}}
        state = parse_gsi_data(data)
        assert state.player_name == "TestPlayer"
        assert state.kills == 5

    def test_parse_abilities(self):
        data = {"hero": {"abilities": {
            "ability0": {"name": "pudge_hook", "level": 4, "can_cast": True},
            "ability3": {"name": "pudge_dismember", "ultimate": True},
        }}}
        state = parse_gsi_data(data)
        assert len(state.abilities) == 2
        assert state.abilities[0].name == "pudge_hook"
        assert state.abilities[1].ultimate is True

    def test_parse_items(self):
        data = {"hero": {"items": {
            "slot0": {"name": "blink", "can_cast": True},
            "slot1": {"name": "bkb", "cooldown": 5.0},
        }}}
        state = parse_gsi_data(data)
        assert len(state.inventory) == 2
        assert state.inventory[0].name == "blink"
