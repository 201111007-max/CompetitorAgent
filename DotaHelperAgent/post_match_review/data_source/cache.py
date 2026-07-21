"""比赛数据本地缓存"""
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional

from post_match_review.observability.logger import get_logger
from post_match_review.domain_types.match_data import MatchData

logger = get_logger("data_source.cache")

# 默认缓存 TTL：7 天（秒）
DEFAULT_TTL = 7 * 24 * 60 * 60


class MatchDataCache:
    """比赛数据本地缓存"""

    def __init__(
        self,
        cache_dir: str | Path = "data/cache",
        ttl: int = DEFAULT_TTL,
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._ttl = ttl
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, match_id: str) -> Path:
        """获取缓存文件路径"""
        return self._cache_dir / f"{match_id}.json"

    def read(self, match_id: str) -> Optional[MatchData]:
        """读取缓存

        Args:
            match_id: 比赛 ID

        Returns:
            Optional[MatchData]: 缓存命中时返回，未命中或过期返回 None
        """
        cache_path = self._get_cache_path(match_id)
        if not cache_path.exists():
            logger.debug("缓存未命中: match_id=%s", match_id)
            return None

        # 检查 TTL
        mtime = cache_path.stat().st_mtime
        if time.time() - mtime > self._ttl:
            logger.info("缓存已过期: match_id=%s", match_id)
            cache_path.unlink()
            return None

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            match_data = self._dict_to_match_data(data)
            logger.info("缓存命中: match_id=%s", match_id)
            return match_data
        except Exception as e:
            logger.warning("缓存读取失败: %s", str(e))
            return None

    def write(self, match_data: MatchData) -> None:
        """写入缓存

        Args:
            match_data: 比赛数据
        """
        cache_path = self._get_cache_path(match_data.match_id)
        try:
            data = asdict(match_data)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("缓存写入成功: match_id=%s", match_data.match_id)
        except Exception as e:
            logger.warning("缓存写入失败: %s", str(e))

    def clear(self, match_id: Optional[str] = None) -> None:
        """清除缓存

        Args:
            match_id: 指定比赛 ID 时仅清除该缓存，None 时清除全部
        """
        if match_id:
            cache_path = self._get_cache_path(match_id)
            if cache_path.exists():
                cache_path.unlink()
                logger.info("缓存已清除: match_id=%s", match_id)
        else:
            for f in self._cache_dir.glob("*.json"):
                f.unlink()
            logger.info("全部缓存已清除")

    def _dict_to_match_data(self, data: Dict[str, Any]) -> MatchData:
        """将字典转换回 MatchData"""
        from post_match_review.domain_types.match_data import (
            EconomyData,
            LaneData,
            PickBan,
            PlayerData,
            TeamfightData,
        )

        players = [PlayerData(**p) for p in data.get("players", [])]
        picks_bans = [PickBan(**pb) for pb in data.get("picks_bans", [])]

        lane_data = None
        if data.get("lane_data"):
            lane_data = LaneData(**data["lane_data"])

        teamfight_data = None
        if data.get("teamfight_data"):
            teamfight_data = [TeamfightData(**tf) for tf in data["teamfight_data"]]

        economy_data = None
        if data.get("economy_data"):
            economy_data = EconomyData(**data["economy_data"])

        return MatchData(
            match_id=data["match_id"],
            duration=data["duration"],
            radiant_win=data["radiant_win"],
            radiant_score=data["radiant_score"],
            dire_score=data["dire_score"],
            game_mode=data["game_mode"],
            players=players,
            picks_bans=picks_bans,
            lane_data=lane_data,
            teamfight_data=teamfight_data,
            economy_data=economy_data,
            raw_metadata=data.get("raw_metadata", {}),
        )
