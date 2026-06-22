"""GSI 数据模型

定义游戏状态、技能、物品、事件等数据结构
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any
import time


@dataclass
class AbilityInfo:
    """技能信息"""
    name: str = ""
    level: int = 0
    can_cast: bool = False
    passive: bool = False
    cooldown: float = 0.0
    ultimate: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "level": self.level,
            "can_cast": self.can_cast,
            "passive": self.passive,
            "cooldown": self.cooldown,
            "ultimate": self.ultimate,
        }


@dataclass
class ItemInfo:
    """物品信息"""
    name: str = ""
    slot: str = ""
    can_cast: bool = False
    cooldown: float = 0.0
    charges: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "slot": self.slot,
            "can_cast": self.can_cast,
            "cooldown": self.cooldown,
            "charges": self.charges,
        }


@dataclass
class GameState:
    """完整游戏状态"""
    # 地图
    map_name: str = ""
    match_id: str = ""
    game_time: int = 0
    clock_time: int = 0
    daytime: bool = True
    radiant_score: int = 0
    dire_score: int = 0
    game_state: str = ""
    paused: bool = False
    win_team: str = ""

    # 玩家
    player_name: str = ""
    steam_id: str = ""
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    last_hits: int = 0
    denies: int = 0
    gold: int = 0
    gold_reliable: int = 0
    gpm: int = 0
    xpm: int = 0

    # 英雄
    hero_name: str = ""
    hero_id: int = 0
    level: int = 1
    alive: bool = True
    respawn_seconds: int = 0
    health: int = 0
    max_health: int = 0
    mana: int = 0
    max_mana: int = 0
    buyback_cost: int = 0

    # 技能和物品
    abilities: List[AbilityInfo] = field(default_factory=list)
    inventory: List[ItemInfo] = field(default_factory=list)

    # 元数据
    updated_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "map_name": self.map_name,
            "match_id": self.match_id,
            "game_time": self.game_time,
            "clock_time": self.clock_time,
            "daytime": self.daytime,
            "radiant_score": self.radiant_score,
            "dire_score": self.dire_score,
            "game_state": self.game_state,
            "paused": self.paused,
            "win_team": self.win_team,
            "player_name": self.player_name,
            "steam_id": self.steam_id,
            "kills": self.kills,
            "deaths": self.deaths,
            "assists": self.assists,
            "last_hits": self.last_hits,
            "denies": self.denies,
            "gold": self.gold,
            "gold_reliable": self.gold_reliable,
            "gpm": self.gpm,
            "xpm": self.xpm,
            "hero_name": self.hero_name,
            "hero_id": self.hero_id,
            "level": self.level,
            "alive": self.alive,
            "respawn_seconds": self.respawn_seconds,
            "health": self.health,
            "max_health": self.max_health,
            "mana": self.mana,
            "max_mana": self.max_mana,
            "buyback_cost": self.buyback_cost,
            "abilities": [a.to_dict() for a in self.abilities],
            "inventory": [i.to_dict() for i in self.inventory],
            "updated_at": self.updated_at,
        }


@dataclass
class GSIEvent:
    """GSI 事件"""
    event_type: str
    message: str
    priority: str = "info"
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "message": self.message,
            "priority": self.priority,
            "data": self.data,
            "timestamp": self.timestamp,
        }


def parse_gsi_data(gsi_data: Dict[str, Any]) -> GameState:
    """解析 GSI 推送的原始 JSON 数据为 GameState"""
    state = GameState()

    # 解析 provider
    provider = gsi_data.get("provider", {})
    if provider:
        state.map_name = provider.get("name", "")

    # 解析 map
    map_data = gsi_data.get("map", {})
    if map_data:
        state.match_id = str(map_data.get("matchid", ""))
        state.game_time = map_data.get("game_time", 0)
        state.clock_time = map_data.get("clock_time", 0)
        state.daytime = map_data.get("daytime", True)
        state.radiant_score = map_data.get("radiant_score", 0)
        state.dire_score = map_data.get("dire_score", 0)
        state.game_state = map_data.get("game_state", "")
        state.paused = map_data.get("paused", False)
        state.win_team = map_data.get("win_team", "")

    # 解析 hero
    hero_data = gsi_data.get("hero", {})
    if hero_data:
        state.hero_name = hero_data.get("name", "")
        state.hero_id = hero_data.get("id", 0)
        state.level = hero_data.get("level", 1)
        state.alive = hero_data.get("alive", True)
        state.respawn_seconds = hero_data.get("respawn_seconds", 0)
        state.buyback_cost = hero_data.get("buyback_cost", 0)

        hp = hero_data.get("health", 0)
        max_hp = hero_data.get("max_health", 0)
        if isinstance(hp, (int, float)):
            state.health = int(hp)
        if isinstance(max_hp, (int, float)):
            state.max_health = int(max_hp)

        mp = hero_data.get("mana", 0)
        max_mp = hero_data.get("max_mana", 0)
        if isinstance(mp, (int, float)):
            state.mana = int(mp)
        if isinstance(max_mp, (int, float)):
            state.max_mana = int(max_mp)

        # 技能
        abilities = hero_data.get("abilities", {})
        if isinstance(abilities, dict):
            for _slot, ab in abilities.items():
                if isinstance(ab, dict):
                    state.abilities.append(AbilityInfo(
                        name=ab.get("name", ""),
                        level=ab.get("level", 0),
                        can_cast=ab.get("can_cast", False),
                        passive=ab.get("passive", False),
                        cooldown=ab.get("cooldown", 0.0),
                        ultimate=ab.get("ultimate", False),
                    ))

        # 物品
        items_data = hero_data.get("items", {})
        if isinstance(items_data, dict):
            for slot, item in items_data.items():
                if isinstance(item, dict):
                    state.inventory.append(ItemInfo(
                        name=item.get("name", ""),
                        slot=slot,
                        can_cast=item.get("can_cast", False),
                        cooldown=item.get("cooldown", 0.0),
                        charges=item.get("charges", 0),
                    ))

    # 解析 player
    player_data = gsi_data.get("player", {})
    if player_data:
        state.player_name = player_data.get("name", "")
        state.steam_id = str(player_data.get("steamid", ""))
        state.kills = player_data.get("kills", 0)
        state.deaths = player_data.get("deaths", 0)
        state.assists = player_data.get("assists", 0)
        state.last_hits = player_data.get("last_hits", 0)
        state.denies = player_data.get("denies", 0)
        state.gold = player_data.get("gold", 0)
        state.gold_reliable = player_data.get("gold_reliable", 0)
        state.gpm = player_data.get("gpm", 0)
        state.xpm = player_data.get("xpm", 0)

    state.updated_at = time.time()
    return state
