"""比赛数据模型定义"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class PlayerData:
    """玩家数据"""
    account_id: Optional[str]
    hero_id: int
    hero_name: str
    kills: int
    deaths: int
    assists: int
    last_hits: int
    denies: int
    gpm: int
    xpm: int
    hero_damage: int
    tower_damage: int
    is_radiant: bool
    is_user: bool
    items: List[int] = field(default_factory=list)
    level: int = 1
    gold: int = 0
    xp_per_min: int = 0
    additional_fields: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PickBan:
    """Ban/Pick 记录"""
    is_pick: bool
    hero_id: int
    team: int  # 0: 天辉, 1: 夜魇
    order: int


@dataclass
class LaneData:
    """对线期数据"""
    player_lane: Dict[str, int]  # account_id -> lane (1-5)
    lh_at_10: Dict[str, int]     # account_id -> 10 分钟补刀
    denies_at_10: Dict[str, int]
    hero_damage_at_10: Dict[str, int]
    networth_at_10: Dict[str, int]


@dataclass
class TeamfightData:
    """团战数据"""
    start: int              # 起始时间（秒）
    end: int
    deaths: int
    players: List[str]      # 参与玩家 account_id 列表
    radiant_gold_delta: int
    dire_gold_delta: int


@dataclass
class EconomyData:
    """经济数据"""
    gpm_series: Dict[str, List[int]]   # account_id -> 每分钟 GPM
    xpm_series: Dict[str, List[int]]
    networth_series: Dict[str, List[int]]
    purchase_log: Dict[str, List[Dict[str, Any]]]


@dataclass
class MatchData:
    """结构化比赛数据"""
    match_id: str
    duration: int
    radiant_win: bool
    radiant_score: int
    dire_score: int
    game_mode: int
    players: List[PlayerData]
    picks_bans: List[PickBan]
    lane_data: Optional[LaneData] = None
    teamfight_data: Optional[List[TeamfightData]] = None
    economy_data: Optional[EconomyData] = None
    raw_metadata: Dict[str, Any] = field(default_factory=dict)
