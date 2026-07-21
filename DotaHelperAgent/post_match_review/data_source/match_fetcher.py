"""比赛数据获取与结构化转换"""
from typing import Any, Dict, List, Optional

from post_match_review.data_source.exceptions import DataSourceError
from post_match_review.data_source.opendota_client import OpenDotaClient
from post_match_review.observability.logger import get_logger
from post_match_review.domain_types.match_data import (
    EconomyData,
    LaneData,
    MatchData,
    PickBan,
    PlayerData,
    TeamfightData,
)

logger = get_logger("data_source.match_fetcher")

# 英雄 ID -> 名称映射（简化版，实际可从 OpenDota /heroes 接口获取）
HERO_NAMES: Dict[int, str] = {
    1: "Anti-Mage", 2: "Axe", 3: "Bane", 4: "Bloodseeker",
    5: "Crystal Maiden", 6: "Drow Ranger", 7: "Earthshaker",
    8: "Juggernaut", 9: "Mirana", 10: "Morphling",
    11: "Shadow Fiend", 12: "Phantom Lancer", 13: "Puck",
    14: "Pudge", 15: "Razor", 16: "Sand King",
    17: "Storm Spirit", 18: "Sven", 19: "Tiny",
    20: "Vengeful Spirit", 21: "Windranger", 22: "Zeus",
    23: "Kunkka", 25: "Lina", 26: "Lion",
    27: "Shadow Shaman", 28: "Slardar", 29: "Tidehunter",
    30: "Witch Doctor", 31: "Lich", 32: "Riki",
    33: "Enigma", 34: "Tinker", 35: "Sniper",
    36: "Necrophos", 37: "Warlock", 38: "Beastmaster",
    39: "Queen of Pain", 40: "Venomancer", 41: "Faceless Void",
    42: "Wraith King", 43: "Death Prophet", 44: "Phantom Assassin",
    # ... 更多英雄可后续补充
}


def _get_hero_name(hero_id: int) -> str:
    """根据 hero_id 获取英雄名称"""
    return HERO_NAMES.get(hero_id, f"Unknown Hero ({hero_id})")


class MatchFetcher:
    """比赛数据获取与结构化"""

    def __init__(
        self,
        client: OpenDotaClient,
        target_account_id: Optional[str] = None,
    ) -> None:
        self._client = client
        self._target_account_id = target_account_id

    async def fetch_and_parse(self, match_id: str) -> MatchData:
        """获取并解析比赛数据

        Args:
            match_id: 比赛 ID

        Returns:
            MatchData: 结构化比赛数据

        Raises:
            DataSourceError: 数据解析失败
        """
        raw = await self._client.get_match_details(match_id)
        try:
            match_data = self._parse(raw, match_id)
            logger.info(
                "比赛数据解析完成: match_id=%s, duration=%ds, players=%d",
                match_id,
                match_data.duration,
                len(match_data.players),
            )
            return match_data
        except Exception as e:
            raise DataSourceError(f"比赛数据解析失败: {e}") from e

    def _parse(self, raw: Dict[str, Any], match_id: str) -> MatchData:
        """将 OpenDota 原始响应转换为 MatchData"""
        players = self._parse_players(raw.get("players", []))
        picks_bans = self._parse_picks_bans(raw.get("picks_bans", []))
        lane_data = self._parse_lane_data(raw.get("players", []))
        teamfight_data = self._parse_teamfights(raw.get("teamfights", []))
        economy_data = self._parse_economy(raw.get("players", []))

        radiant_score = raw.get("radiant_score", 0)
        dire_score = raw.get("dire_score", 0)

        return MatchData(
            match_id=match_id,
            duration=raw.get("duration", 0),
            radiant_win=raw.get("radiant_win", False),
            radiant_score=radiant_score,
            dire_score=dire_score,
            game_mode=raw.get("game_mode", 0),
            players=players,
            picks_bans=picks_bans,
            lane_data=lane_data,
            teamfight_data=teamfight_data if teamfight_data else None,
            economy_data=economy_data if economy_data else None,
            raw_metadata=raw,
        )

    def _parse_players(self, raw_players: List[Dict[str, Any]]) -> List[PlayerData]:
        """解析玩家列表"""
        players: List[PlayerData] = []
        target_found = False

        for p in raw_players:
            account_id = str(p["account_id"]) if p.get("account_id") else None
            is_user = False

            if self._target_account_id and account_id == self._target_account_id:
                is_user = True
                target_found = True

            hero_id = p.get("hero_id", 0)
            player = PlayerData(
                account_id=account_id,
                hero_id=hero_id,
                hero_name=p.get("hero_name") or _get_hero_name(hero_id),
                kills=p.get("kills", 0),
                deaths=p.get("deaths", 0),
                assists=p.get("assists", 0),
                last_hits=p.get("last_hits", 0),
                denies=p.get("denies", 0),
                gpm=p.get("gold_per_min", 0),
                xpm=p.get("xp_per_min", 0),
                hero_damage=p.get("hero_damage", 0),
                tower_damage=p.get("tower_damage", 0),
                is_radiant=p.get("isRadiant", True),
                is_user=is_user,
                items=[p.get(f"item_{i}", 0) for i in range(6)],
                level=p.get("level", 1),
                gold=p.get("gold", 0),
                xp_per_min=p.get("xp_per_min", 0),
            )
            players.append(player)

        # 未找到目标用户时，标记第一个玩家并记录警告
        if self._target_account_id and not target_found:
            logger.warning(
                "目标用户 %s 未在比赛中找到，默认标记第一个玩家",
                self._target_account_id,
            )
            if players:
                players[0].is_user = True
        elif not self._target_account_id and players:
            # 未配置目标用户，默认标记第一个
            players[0].is_user = True
            logger.warning("未配置 target_account_id，默认标记第一个玩家")

        return players

    def _parse_picks_bans(self, raw_picks_bans: List[Dict[str, Any]]) -> List[PickBan]:
        """解析 Ban/Pick 记录"""
        return [
            PickBan(
                is_pick=pb.get("is_pick", True),
                hero_id=pb.get("hero_id", 0),
                team=pb.get("team", 0),
                order=pb.get("order", 0),
            )
            for pb in raw_picks_bans
        ]

    def _parse_lane_data(self, raw_players: List[Dict[str, Any]]) -> LaneData:
        """解析对线期数据"""
        player_lane: Dict[str, int] = {}
        lh_at_10: Dict[str, int] = {}
        denies_at_10: Dict[str, int] = {}
        hero_damage_at_10: Dict[str, int] = {}
        networth_at_10: Dict[str, int] = {}

        for p in raw_players:
            account_id = str(p.get("account_id", ""))
            if not account_id:
                continue

            player_lane[account_id] = p.get("lane", 0)
            lh_at_10[account_id] = p.get("lh_t", [0] * 60)[10] if len(p.get("lh_t", [])) > 10 else 0
            denies_at_10[account_id] = p.get("denies_t", [0] * 60)[10] if len(p.get("denies_t", [])) > 10 else 0
            hero_damage_at_10[account_id] = p.get("hero_damage_at_10", 0)
            networth_at_10[account_id] = p.get("net_worth_at_10", 0)

        return LaneData(
            player_lane=player_lane,
            lh_at_10=lh_at_10,
            denies_at_10=denies_at_10,
            hero_damage_at_10=hero_damage_at_10,
            networth_at_10=networth_at_10,
        )

    def _parse_teamfights(self, raw_teamfights: List[Dict[str, Any]]) -> List[TeamfightData]:
        """解析团战数据"""
        result: List[TeamfightData] = []
        for tf in raw_teamfights:
            players = []
            for p in tf.get("players", []):
                if p.get("participation", False):
                    aid = str(p.get("account_id", ""))
                    if aid:
                        players.append(aid)

            result.append(TeamfightData(
                start=tf.get("start", 0),
                end=tf.get("end", 0),
                deaths=tf.get("deaths", 0),
                players=players,
                radiant_gold_delta=tf.get("radiant_gold_delta", 0),
                dire_gold_delta=tf.get("dire_gold_delta", 0),
            ))
        return result

    def _parse_economy(self, raw_players: List[Dict[str, Any]]) -> EconomyData:
        """解析经济数据"""
        gpm_series: Dict[str, List[int]] = {}
        xpm_series: Dict[str, List[int]] = {}
        networth_series: Dict[str, List[int]] = {}
        purchase_log: Dict[str, List[Dict[str, Any]]] = {}

        for p in raw_players:
            account_id = str(p.get("account_id", ""))
            if not account_id:
                continue

            gpm_series[account_id] = p.get("gold_t", [])
            xpm_series[account_id] = p.get("xp_t", [])
            networth_series[account_id] = p.get("net_worth_t", [])
            purchase_log[account_id] = p.get("purchase_log", [])

        return EconomyData(
            gpm_series=gpm_series,
            xpm_series=xpm_series,
            networth_series=networth_series,
            purchase_log=purchase_log,
        )
