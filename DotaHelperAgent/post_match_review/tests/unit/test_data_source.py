"""数据源层单元测试"""
import asyncio
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from post_match_review.data_source.cache import MatchDataCache
from post_match_review.data_source.data_validator import DataValidator
from post_match_review.data_source.exceptions import (
    DataValidationError,
    DataSourceError,
    OpenDotaAPIError,
)
from post_match_review.data_source.match_fetcher import MatchFetcher
from post_match_review.data_source.opendota_client import OpenDotaClient
from post_match_review.types.match_data import (
    EconomyData,
    LaneData,
    MatchData,
    PickBan,
    PlayerData,
    TeamfightData,
)


# ============================================================================
# OpenDotaClient 测试
# ============================================================================


class TestOpenDotaClient:
    """OpenDotaClient 单元测试"""

    @pytest.mark.asyncio
    async def test_get_match_details_success(self, sample_match_data: Dict[str, Any]) -> None:
        """测试成功获取比赛详情"""
        with respx.mock:
            respx.get("https://api.opendota.com/api/matches/8893253595").mock(
                return_value=httpx.Response(200, json=sample_match_data)
            )

            client = OpenDotaClient()
            result = await client.get_match_details("8893253595")
            await client.close()

            assert result["match_id"] == 8893253595
            assert result["duration"] == 1800

    @pytest.mark.asyncio
    async def test_get_match_details_retry_on_500(self) -> None:
        """测试 500 错误时重试"""
        with respx.mock:
            route = respx.get("https://api.opendota.com/api/matches/123")
            route.side_effect = [
                httpx.Response(500, text="Internal Server Error"),
                httpx.Response(500, text="Internal Server Error"),
                httpx.Response(200, json={"match_id": 123}),
            ]

            client = OpenDotaClient(max_retries=3)
            result = await client.get_match_details("123")
            await client.close()

            assert result["match_id"] == 123
            assert route.call_count == 3

    @pytest.mark.asyncio
    async def test_get_match_details_no_retry_on_404(self) -> None:
        """测试 404 错误时不重试"""
        with respx.mock:
            route = respx.get("https://api.opendota.com/api/matches/999")
            route.mock(return_value=httpx.Response(404, text="Not Found"))

            client = OpenDotaClient()
            with pytest.raises(OpenDotaAPIError) as exc_info:
                await client.get_match_details("999")
            await client.close()

            assert exc_info.value.status_code == 404
            assert route.call_count == 1

    @pytest.mark.asyncio
    async def test_get_match_details_retry_on_429(self) -> None:
        """测试 429 限流时重试"""
        with respx.mock:
            route = respx.get("https://api.opendota.com/api/matches/456")
            route.side_effect = [
                httpx.Response(429, text="Too Many Requests"),
                httpx.Response(200, json={"match_id": 456}),
            ]

            client = OpenDotaClient(max_retries=2)
            result = await client.get_match_details("456")
            await client.close()

            assert result["match_id"] == 456
            assert route.call_count == 2

    @pytest.mark.asyncio
    async def test_get_match_details_network_error_retry(self) -> None:
        """测试网络错误时重试"""
        with respx.mock:
            route = respx.get("https://api.opendota.com/api/matches/789")
            route.side_effect = [
                httpx.ConnectError("Connection failed"),
                httpx.Response(200, json={"match_id": 789}),
            ]

            client = OpenDotaClient(max_retries=2)
            result = await client.get_match_details("789")
            await client.close()

            assert result["match_id"] == 789
            assert route.call_count == 2

    @pytest.mark.asyncio
    async def test_get_match_details_max_retries_exceeded(self) -> None:
        """测试超过最大重试次数"""
        with respx.mock:
            route = respx.get("https://api.opendota.com/api/matches/111")
            route.side_effect = [
                httpx.Response(500, text="Error"),
                httpx.Response(500, text="Error"),
                httpx.Response(500, text="Error"),
            ]

            client = OpenDotaClient(max_retries=3)
            with pytest.raises(OpenDotaAPIError) as exc_info:
                await client.get_match_details("111")
            await client.close()

            assert "已重试 3 次" in str(exc_info.value)
            assert route.call_count == 3


# ============================================================================
# MatchFetcher 测试
# ============================================================================


class TestMatchFetcher:
    """MatchFetcher 单元测试"""

    @pytest.mark.asyncio
    async def test_fetch_and_parse_success(self, sample_match_data: Dict[str, Any]) -> None:
        """测试成功获取并解析比赛数据"""
        mock_client = AsyncMock(spec=OpenDotaClient)
        mock_client.get_match_details.return_value = sample_match_data

        fetcher = MatchFetcher(client=mock_client, target_account_id="123456789")
        result = await fetcher.fetch_and_parse("8893253595")

        assert result.match_id == "8893253595"
        assert result.duration == 1800
        assert result.radiant_win is True
        assert result.radiant_score == 35
        assert result.dire_score == 20
        assert len(result.players) == 10
        assert len(result.picks_bans) == 3

    @pytest.mark.asyncio
    async def test_parse_players_with_target_user(self, sample_match_data: Dict[str, Any]) -> None:
        """测试目标用户识别"""
        mock_client = AsyncMock(spec=OpenDotaClient)
        mock_client.get_match_details.return_value = sample_match_data

        fetcher = MatchFetcher(client=mock_client, target_account_id="100000000")
        result = await fetcher.fetch_and_parse("8893253595")

        user_players = [p for p in result.players if p.is_user]
        assert len(user_players) == 1
        assert user_players[0].account_id == "100000000"

    @pytest.mark.asyncio
    async def test_parse_players_default_first_user(self, sample_match_data: Dict[str, Any]) -> None:
        """测试未配置目标用户时默认标记第一个"""
        mock_client = AsyncMock(spec=OpenDotaClient)
        mock_client.get_match_details.return_value = sample_match_data

        fetcher = MatchFetcher(client=mock_client)
        result = await fetcher.fetch_and_parse("8893253595")

        user_players = [p for p in result.players if p.is_user]
        assert len(user_players) == 1
        assert user_players[0] == result.players[0]

    @pytest.mark.asyncio
    async def test_parse_players_target_not_found(self, sample_match_data: Dict[str, Any]) -> None:
        """测试目标用户未找到时默认标记第一个"""
        mock_client = AsyncMock(spec=OpenDotaClient)
        mock_client.get_match_details.return_value = sample_match_data

        fetcher = MatchFetcher(client=mock_client, target_account_id="999999999")
        result = await fetcher.fetch_and_parse("8893253595")

        user_players = [p for p in result.players if p.is_user]
        assert len(user_players) == 1
        assert user_players[0] == result.players[0]

    @pytest.mark.asyncio
    async def test_parse_picks_bans(self, sample_match_data: Dict[str, Any]) -> None:
        """测试 Ban/Pick 解析"""
        mock_client = AsyncMock(spec=OpenDotaClient)
        mock_client.get_match_details.return_value = sample_match_data

        fetcher = MatchFetcher(client=mock_client)
        result = await fetcher.fetch_and_parse("8893253595")

        assert len(result.picks_bans) == 3
        assert result.picks_bans[0].is_pick is True
        assert result.picks_bans[0].hero_id == 8
        assert result.picks_bans[2].is_pick is False

    @pytest.mark.asyncio
    async def test_parse_teamfight_data(self, sample_match_data: Dict[str, Any]) -> None:
        """测试团战数据解析"""
        mock_client = AsyncMock(spec=OpenDotaClient)
        mock_client.get_match_details.return_value = sample_match_data

        fetcher = MatchFetcher(client=mock_client)
        result = await fetcher.fetch_and_parse("8893253595")

        assert result.teamfight_data is not None
        assert len(result.teamfight_data) == 1
        tf = result.teamfight_data[0]
        assert tf.start == 600
        assert tf.end == 650
        assert tf.deaths == 5
        assert len(tf.players) == 2

    @pytest.mark.asyncio
    async def test_parse_economy_data(self, sample_match_data: Dict[str, Any]) -> None:
        """测试经济数据解析"""
        mock_client = AsyncMock(spec=OpenDotaClient)
        mock_client.get_match_details.return_value = sample_match_data

        fetcher = MatchFetcher(client=mock_client)
        result = await fetcher.fetch_and_parse("8893253595")

        assert result.economy_data is not None
        assert len(result.economy_data.gpm_series) == 10
        assert len(result.economy_data.purchase_log) == 10


# ============================================================================
# DataValidator 测试
# ============================================================================


class TestDataValidator:
    """DataValidator 单元测试"""

    def test_validate_success(self) -> None:
        """测试校验通过"""
        match_data = MatchData(
            match_id="8893253595",
            duration=1800,
            radiant_win=True,
            radiant_score=35,
            dire_score=20,
            game_mode=22,
            players=[
                PlayerData(
                    account_id=str(i),
                    hero_id=i + 1,
                    hero_name=f"Hero {i}",
                    kills=0,
                    deaths=0,
                    assists=0,
                    last_hits=0,
                    denies=0,
                    gpm=0,
                    xpm=0,
                    hero_damage=0,
                    tower_damage=0,
                    is_radiant=i < 5,
                    is_user=i == 0,
                )
                for i in range(10)
            ],
            picks_bans=[],
        )

        validator = DataValidator()
        is_valid, errors = validator.validate(match_data)

        assert is_valid is True
        assert errors == []

    def test_validate_empty_match_id(self) -> None:
        """测试空 match_id"""
        match_data = MatchData(
            match_id="",
            duration=1800,
            radiant_win=True,
            radiant_score=35,
            dire_score=20,
            game_mode=22,
            players=[
                PlayerData(
                    account_id=str(i),
                    hero_id=i + 1,
                    hero_name=f"Hero {i}",
                    kills=0,
                    deaths=0,
                    assists=0,
                    last_hits=0,
                    denies=0,
                    gpm=0,
                    xpm=0,
                    hero_damage=0,
                    tower_damage=0,
                    is_radiant=i < 5,
                    is_user=i == 0,
                )
                for i in range(10)
            ],
            picks_bans=[],
        )

        validator = DataValidator()
        is_valid, errors = validator.validate(match_data)

        assert is_valid is False
        assert "match_id 为空" in errors

    def test_validate_duration_too_short(self) -> None:
        """测试比赛时长过短"""
        match_data = MatchData(
            match_id="123",
            duration=30,  # 低于 60 秒
            radiant_win=True,
            radiant_score=5,
            dire_score=3,
            game_mode=22,
            players=[
                PlayerData(
                    account_id=str(i),
                    hero_id=i + 1,
                    hero_name=f"Hero {i}",
                    kills=0,
                    deaths=0,
                    assists=0,
                    last_hits=0,
                    denies=0,
                    gpm=0,
                    xpm=0,
                    hero_damage=0,
                    tower_damage=0,
                    is_radiant=i < 5,
                    is_user=i == 0,
                )
                for i in range(10)
            ],
            picks_bans=[],
        )

        validator = DataValidator()
        is_valid, errors = validator.validate(match_data)

        assert is_valid is False
        assert any("比赛时长" in e for e in errors)

    def test_validate_too_few_players(self) -> None:
        """测试玩家数量不足"""
        match_data = MatchData(
            match_id="123",
            duration=1800,
            radiant_win=True,
            radiant_score=10,
            dire_score=5,
            game_mode=22,
            players=[
                PlayerData(
                    account_id="0",
                    hero_id=1,
                    hero_name="Hero 0",
                    kills=0,
                    deaths=0,
                    assists=0,
                    last_hits=0,
                    denies=0,
                    gpm=0,
                    xpm=0,
                    hero_damage=0,
                    tower_damage=0,
                    is_radiant=True,
                    is_user=True,
                )
                for _ in range(5)  # 只有 5 个玩家
            ],
            picks_bans=[],
        )

        validator = DataValidator()
        is_valid, errors = validator.validate(match_data)

        assert is_valid is False
        assert any("玩家数量" in e for e in errors)

    def test_validate_invalid_hero_id(self) -> None:
        """测试无效 hero_id"""
        match_data = MatchData(
            match_id="123",
            duration=1800,
            radiant_win=True,
            radiant_score=10,
            dire_score=5,
            game_mode=22,
            players=[
                PlayerData(
                    account_id=str(i),
                    hero_id=0 if i == 0 else i + 1,  # 第一个玩家 hero_id 为 0
                    hero_name=f"Hero {i}",
                    kills=0,
                    deaths=0,
                    assists=0,
                    last_hits=0,
                    denies=0,
                    gpm=0,
                    xpm=0,
                    hero_damage=0,
                    tower_damage=0,
                    is_radiant=i < 5,
                    is_user=i == 0,
                )
                for i in range(10)
            ],
            picks_bans=[],
        )

        validator = DataValidator()
        is_valid, errors = validator.validate(match_data)

        assert is_valid is False
        assert any("hero_id 无效" in e for e in errors)


# ============================================================================
# MatchDataCache 测试
# ============================================================================


class TestMatchDataCache:
    """MatchDataCache 单元测试"""

    def test_cache_write_and_read(self, tmp_path: Path) -> None:
        """测试缓存写入和读取"""
        cache = MatchDataCache(cache_dir=tmp_path, ttl=3600)

        match_data = MatchData(
            match_id="test_123",
            duration=1800,
            radiant_win=True,
            radiant_score=35,
            dire_score=20,
            game_mode=22,
            players=[
                PlayerData(
                    account_id="123",
                    hero_id=8,
                    hero_name="Juggernaut",
                    kills=10,
                    deaths=2,
                    assists=15,
                    last_hits=250,
                    denies=15,
                    gpm=650,
                    xpm=700,
                    hero_damage=25000,
                    tower_damage=8000,
                    is_radiant=True,
                    is_user=True,
                )
            ],
            picks_bans=[
                PickBan(is_pick=True, hero_id=8, team=0, order=0),
            ],
        )

        # 写入缓存
        cache.write(match_data)

        # 读取缓存
        cached = cache.read("test_123")
        assert cached is not None
        assert cached.match_id == "test_123"
        assert cached.duration == 1800
        assert len(cached.players) == 1
        assert cached.players[0].hero_name == "Juggernaut"

    def test_cache_miss(self, tmp_path: Path) -> None:
        """测试缓存未命中"""
        cache = MatchDataCache(cache_dir=tmp_path)
        result = cache.read("nonexistent_match")
        assert result is None

    def test_cache_ttl_expiration(self, tmp_path: Path) -> None:
        """测试缓存 TTL 过期"""
        cache = MatchDataCache(cache_dir=tmp_path, ttl=1)  # 1 秒 TTL

        match_data = MatchData(
            match_id="ttl_test",
            duration=1800,
            radiant_win=True,
            radiant_score=10,
            dire_score=5,
            game_mode=22,
            players=[],
            picks_bans=[],
        )

        cache.write(match_data)

        # 立即读取应该命中
        cached = cache.read("ttl_test")
        assert cached is not None

        # 等待 TTL 过期
        time.sleep(1.5)

        # 过期后应该返回 None
        cached = cache.read("ttl_test")
        assert cached is None

    def test_cache_clear_specific(self, tmp_path: Path) -> None:
        """测试清除特定缓存"""
        cache = MatchDataCache(cache_dir=tmp_path)

        match_data = MatchData(
            match_id="clear_test",
            duration=1800,
            radiant_win=True,
            radiant_score=10,
            dire_score=5,
            game_mode=22,
            players=[],
            picks_bans=[],
        )

        cache.write(match_data)
        assert cache.read("clear_test") is not None

        cache.clear("clear_test")
        assert cache.read("clear_test") is None

    def test_cache_clear_all(self, tmp_path: Path) -> None:
        """测试清除全部缓存"""
        cache = MatchDataCache(cache_dir=tmp_path)

        for i in range(3):
            match_data = MatchData(
                match_id=f"match_{i}",
                duration=1800,
                radiant_win=True,
                radiant_score=10,
                dire_score=5,
                game_mode=22,
                players=[],
                picks_bans=[],
            )
            cache.write(match_data)

        # 验证都写入了
        for i in range(3):
            assert cache.read(f"match_{i}") is not None

        # 清除全部
        cache.clear()

        # 验证都清除了
        for i in range(3):
            assert cache.read(f"match_{i}") is None

    def test_cache_with_optional_fields(self, tmp_path: Path) -> None:
        """测试包含可选字段的缓存"""
        cache = MatchDataCache(cache_dir=tmp_path)

        match_data = MatchData(
            match_id="optional_test",
            duration=1800,
            radiant_win=True,
            radiant_score=35,
            dire_score=20,
            game_mode=22,
            players=[
                PlayerData(
                    account_id="123",
                    hero_id=8,
                    hero_name="Juggernaut",
                    kills=10,
                    deaths=2,
                    assists=15,
                    last_hits=250,
                    denies=15,
                    gpm=650,
                    xpm=700,
                    hero_damage=25000,
                    tower_damage=8000,
                    is_radiant=True,
                    is_user=True,
                )
            ],
            picks_bans=[],
            lane_data=LaneData(
                player_lane={"123": 1},
                lh_at_10={"123": 125},
                denies_at_10={"123": 15},
                hero_damage_at_10={"123": 5000},
                networth_at_10={"123": 8000},
            ),
            teamfight_data=[
                TeamfightData(
                    start=600,
                    end=650,
                    deaths=5,
                    players=["123"],
                    radiant_gold_delta=2000,
                    dire_gold_delta=-2000,
                )
            ],
            economy_data=EconomyData(
                gpm_series={"123": [0, 500, 1000]},
                xpm_series={"123": [0, 400, 800]},
                networth_series={"123": [0, 600, 1200]},
                purchase_log={"123": [{"time": 120, "key": "boots"}]},
            ),
        )

        cache.write(match_data)
        cached = cache.read("optional_test")

        assert cached is not None
        assert cached.lane_data is not None
        assert cached.lane_data.lh_at_10["123"] == 125
        assert cached.teamfight_data is not None
        assert len(cached.teamfight_data) == 1
        assert cached.economy_data is not None
        assert cached.economy_data.gpm_series["123"] == [0, 500, 1000]
