"""DataFormatter 通用数据格式化器单元测试"""
import pytest
from typing import List, Dict, Any

from post_match_review.engines.data_formatter import DataFormatter
from post_match_review.domain_types.match_data import (
    MatchData, PlayerData, LaneData, TeamfightData, PickBan,
)


class TestExtractField:
    """测试 _extract_field 路径提取"""

    def test_extract_field_nested_attribute(self) -> None:
        """测试 dataclass 嵌套属性路径"""
        formatter = DataFormatter([])
        lane_data = LaneData(
            player_lane={"acc1": 1},
            lh_at_10={"acc1": 50},
            denies_at_10={"acc1": 5},
            hero_damage_at_10={"acc1": 3000},
            networth_at_10={"acc1": 5000},
        )
        match_data = MatchData(
            match_id="test",
            duration=1800,
            radiant_win=True,
            radiant_score=30,
            dire_score=20,
            game_mode=22,
            players=[],
            picks_bans=[],
            lane_data=lane_data,
        )

        result = formatter._extract_field(match_data, "lane_data.lh_at_10")
        assert result == {"acc1": 50}

    def test_extract_field_dict_key(self) -> None:
        """测试 raw_metadata 字典键路径"""
        formatter = DataFormatter([])
        match_data = MatchData(
            match_id="test",
            duration=1800,
            radiant_win=True,
            radiant_score=30,
            dire_score=20,
            game_mode=22,
            players=[],
            picks_bans=[],
            raw_metadata={"vision": {"obs": {"acc1": [1, 2, 3]}}},
        )

        result = formatter._extract_field(match_data, "raw_metadata.vision")
        assert result == {"obs": {"acc1": [1, 2, 3]}}

    def test_extract_field_nonexistent_path(self) -> None:
        """测试路径不存在返回 None"""
        formatter = DataFormatter([])
        match_data = MatchData(
            match_id="test",
            duration=1800,
            radiant_win=True,
            radiant_score=30,
            dire_score=20,
            game_mode=22,
            players=[],
            picks_bans=[],
        )

        result = formatter._extract_field(match_data, "lane_data.lh_at_10")
        assert result is None

    def test_extract_field_none_intermediate(self) -> None:
        """测试中间路径为 None 时返回 None"""
        formatter = DataFormatter([])
        match_data = MatchData(
            match_id="test",
            duration=1800,
            radiant_win=True,
            radiant_score=30,
            dire_score=20,
            game_mode=22,
            players=[],
            picks_bans=[],
            lane_data=None,
        )

        result = formatter._extract_field(match_data, "lane_data.lh_at_10")
        assert result is None


class TestFormatPlayerStats:
    """测试 _format_player_stats 格式化"""

    def test_format_player_stats_basic(self) -> None:
        """测试基本玩家统计格式化"""
        formatter = DataFormatter([])
        req: Dict[str, Any] = {
            "field": "lane_data.lh_at_10",
            "label": "10分钟补刀数",
            "format": "player_stats",
        }
        data: Dict[str, Any] = {"acc1": 50, "acc2": 40}
        player_map: Dict[str, str] = {"acc1": "Juggernaut", "acc2": "Pudge"}

        result = formatter._format_player_stats(req, data, player_map)

        assert "### 10分钟补刀数" in result
        assert "Juggernaut: 50" in result
        assert "Pudge: 40" in result

    def test_format_player_stats_with_suffix(self) -> None:
        """测试带 value_suffix 的格式化"""
        formatter = DataFormatter([])
        req: Dict[str, Any] = {
            "field": "lane_data.hero_damage_at_10",
            "label": "10分钟英雄伤害",
            "format": "player_stats",
            "value_suffix": "伤害",
        }
        data: Dict[str, Any] = {"acc1": 3000}
        player_map: Dict[str, str] = {"acc1": "Juggernaut"}

        result = formatter._format_player_stats(req, data, player_map)

        assert "Juggernaut: 3000 伤害" in result

    def test_format_player_stats_with_secondary(self) -> None:
        """测试带 secondary_field 的联合输出"""
        formatter = DataFormatter([])
        req: Dict[str, Any] = {
            "field": "lane_data.lh_at_10",
            "label": "10分钟补刀与反补",
            "format": "player_stats",
            "value_suffix": "补刀",
            "secondary_field": "lane_data.denies_at_10",
            "secondary_label": "反补",
        }
        primary_data: Dict[str, Any] = {"acc1": 50, "acc2": 40}
        secondary_data: Dict[str, Any] = {"acc1": 5, "acc2": 3}
        player_map: Dict[str, str] = {"acc1": "Juggernaut", "acc2": "Pudge"}

        result = formatter._format_player_stats_with_secondary(
            req, primary_data, secondary_data, player_map,
        )

        assert "### 10分钟补刀与反补" in result
        assert "Juggernaut" in result
        assert "50" in result
        assert "5" in result


class TestFormatPlayerLane:
    """测试 _format_player_lane 格式化"""

    def test_format_player_lane(self) -> None:
        """测试分路名称映射"""
        formatter = DataFormatter([])
        data: Dict[str, int] = {"acc1": 1, "acc2": 2, "acc3": 3}
        player_map: Dict[str, str] = {
            "acc1": "Juggernaut",
            "acc2": "Pudge",
            "acc3": "Axe",
        }

        result = formatter._format_player_lane("分路分配", data, player_map)

        assert "### 分路分配" in result
        assert "Juggernaut: 安全路（优势路）" in result
        assert "Pudge: 中路" in result
        assert "Axe: 劣势路" in result

    def test_format_player_lane_unknown(self) -> None:
        """测试未知分路编号"""
        formatter = DataFormatter([])
        data: Dict[str, int] = {"acc1": 99}
        player_map: Dict[str, str] = {"acc1": "Juggernaut"}

        result = formatter._format_player_lane("分路分配", data, player_map)

        assert "未知分路 (99)" in result


class TestFormatListItems:
    """测试 _format_list_items 格式化"""

    def test_format_list_items_with_dataclass(self) -> None:
        """测试 dataclass 对象列表格式化"""
        formatter = DataFormatter([])
        req: Dict[str, Any] = {
            "field": "teamfight_data",
            "label": "团战列表",
            "format": "list_items",
            "fields": [
                {"source": "start", "label": "开始时间", "transform": "time_minutes"},
                {"source": "start", "label": "", "transform": "time_seconds"},
                {"source": "deaths", "label": "死亡人数"},
                {"source": "radiant_gold_delta", "label": "天辉经济变化", "transform": "signed_int"},
            ],
        }
        data: List[Any] = [
            TeamfightData(
                start=600, end=630, deaths=3,
                players=["acc1", "acc2"],
                radiant_gold_delta=1500, dire_gold_delta=-800,
            ),
        ]
        player_map: Dict[str, str] = {"acc1": "Juggernaut", "acc2": "Pudge"}

        result = formatter._format_list_items(req, data, player_map)

        assert "### 团战列表" in result
        assert "项目 1" in result
        assert "死亡人数: 3" in result
        assert "+1500" in result

    def test_format_list_items_with_dict(self) -> None:
        """测试字典列表格式化"""
        formatter = DataFormatter([])
        req: Dict[str, Any] = {
            "field": "some_list",
            "label": "事件列表",
            "format": "list_items",
            "fields": [
                {"source": "name", "label": "名称"},
                {"source": "value", "label": "值"},
            ],
        }
        data: List[Dict[str, Any]] = [
            {"name": "事件A", "value": 100},
            {"name": "事件B", "value": 200},
        ]
        player_map: Dict[str, str] = {}

        result = formatter._format_list_items(req, data, player_map)

        assert "### 事件列表" in result
        assert "事件A" in result
        assert "100" in result


class TestFormatCustom:
    """测试 custom 格式跳过"""

    def test_format_custom_skip(self) -> None:
        """测试 custom 格式的需求被跳过"""
        formatter = DataFormatter([
            {
                "field": "economy_data",
                "label": "经济数据",
                "format": "custom",
            },
        ])
        match_data = MatchData(
            match_id="test",
            duration=1800,
            radiant_win=True,
            radiant_score=30,
            dire_score=20,
            game_mode=22,
            players=[],
            picks_bans=[],
        )

        result = formatter.format(match_data)

        assert result == ""


class TestFormatIntegration:
    """测试 format() 整体格式化"""

    def test_format_multiple_requirements(self) -> None:
        """测试多需求组合格式化"""
        formatter = DataFormatter([
            {
                "field": "lane_data.lh_at_10",
                "label": "10分钟补刀数",
                "format": "player_stats",
            },
            {
                "field": "lane_data.player_lane",
                "label": "分路分配",
                "format": "player_lane",
            },
        ])
        lane_data = LaneData(
            player_lane={"acc1": 1, "acc2": 2},
            lh_at_10={"acc1": 50, "acc2": 40},
            denies_at_10={"acc1": 5, "acc2": 3},
            hero_damage_at_10={"acc1": 3000, "acc2": 2000},
            networth_at_10={"acc1": 5000, "acc2": 4000},
        )
        match_data = MatchData(
            match_id="test",
            duration=1800,
            radiant_win=True,
            radiant_score=30,
            dire_score=20,
            game_mode=22,
            players=[
                PlayerData(
                    account_id="acc1", hero_id=8, hero_name="Juggernaut",
                    kills=10, deaths=2, assists=15, last_hits=250,
                    denies=15, gpm=650, xpm=700, hero_damage=25000,
                    tower_damage=8000, is_radiant=True, is_user=True,
                ),
                PlayerData(
                    account_id="acc2", hero_id=14, hero_name="Pudge",
                    kills=5, deaths=8, assists=10, last_hits=100,
                    denies=3, gpm=350, xpm=400, hero_damage=15000,
                    tower_damage=2000, is_radiant=False, is_user=False,
                ),
            ],
            picks_bans=[],
            lane_data=lane_data,
        )

        result = formatter.format(match_data)

        assert "10分钟补刀数" in result
        assert "Juggernaut: 50" in result
        assert "分路分配" in result
        assert "安全路" in result

    def test_format_none_value_skip(self) -> None:
        """测试 None 值跳过"""
        formatter = DataFormatter([
            {
                "field": "lane_data.lh_at_10",
                "label": "补刀",
                "format": "player_stats",
            },
            {
                "field": "lane_data.hero_damage_at_10",
                "label": "伤害",
                "format": "player_stats",
            },
        ])
        lane_data = LaneData(
            player_lane={"acc1": 1},
            lh_at_10={"acc1": 50},
            denies_at_10={"acc1": 5},
            hero_damage_at_10={},
            networth_at_10={"acc1": 5000},
        )
        match_data = MatchData(
            match_id="test",
            duration=1800,
            radiant_win=True,
            radiant_score=30,
            dire_score=20,
            game_mode=22,
            players=[
                PlayerData(
                    account_id="acc1", hero_id=8, hero_name="Juggernaut",
                    kills=10, deaths=2, assists=15, last_hits=250,
                    denies=15, gpm=650, xpm=700, hero_damage=25000,
                    tower_damage=8000, is_radiant=True, is_user=True,
                ),
            ],
            picks_bans=[],
            lane_data=lane_data,
        )

        result = formatter.format(match_data)

        assert "补刀" in result
        # hero_damage_at_10 为空字典，不是 None，所以仍会输出（只是内容为空）

    def test_format_with_secondary_field(self) -> None:
        """测试 format_with_secondary 支持 secondary_field 联合输出"""
        formatter = DataFormatter([
            {
                "field": "lane_data.lh_at_10",
                "label": "10分钟补刀与反补",
                "format": "player_stats",
                "value_suffix": "补刀",
                "secondary_field": "lane_data.denies_at_10",
                "secondary_label": "反补",
            },
        ])
        lane_data = LaneData(
            player_lane={"acc1": 1},
            lh_at_10={"acc1": 50},
            denies_at_10={"acc1": 5},
            hero_damage_at_10={"acc1": 3000},
            networth_at_10={"acc1": 5000},
        )
        match_data = MatchData(
            match_id="test",
            duration=1800,
            radiant_win=True,
            radiant_score=30,
            dire_score=20,
            game_mode=22,
            players=[
                PlayerData(
                    account_id="acc1", hero_id=8, hero_name="Juggernaut",
                    kills=10, deaths=2, assists=15, last_hits=250,
                    denies=15, gpm=650, xpm=700, hero_damage=25000,
                    tower_damage=8000, is_radiant=True, is_user=True,
                ),
            ],
            picks_bans=[],
            lane_data=lane_data,
        )

        result = formatter.format_with_secondary(match_data)

        assert "10分钟补刀与反补" in result
        assert "Juggernaut" in result
        assert "50" in result
        assert "5" in result


class TestHasDeclarativeRequirements:
    """测试 has_declarative_requirements 静态方法"""

    def test_has_declarative_with_non_custom(self) -> None:
        """测试包含非 custom 格式时返回 True"""
        template: Dict[str, Any] = {
            "data_requirements": [
                {"field": "lane_data.lh_at_10", "format": "player_stats"},
                {"field": "economy_data", "format": "custom"},
            ],
        }

        assert DataFormatter.has_declarative_requirements(template) is True

    def test_has_declarative_all_custom(self) -> None:
        """测试全部为 custom 格式时返回 False"""
        template: Dict[str, Any] = {
            "data_requirements": [
                {"field": "economy_data", "format": "custom"},
            ],
        }

        assert DataFormatter.has_declarative_requirements(template) is False

    def test_has_declarative_no_requirements(self) -> None:
        """测试无 data_requirements 时返回 False"""
        template: Dict[str, Any] = {}

        assert DataFormatter.has_declarative_requirements(template) is False

    def test_has_declarative_empty_requirements(self) -> None:
        """测试空 data_requirements 列表时返回 False"""
        template: Dict[str, Any] = {"data_requirements": []}

        assert DataFormatter.has_declarative_requirements(template) is False


class TestApplyTransform:
    """测试 _apply_transform 值变换"""

    def test_transform_time_minutes(self) -> None:
        """测试 time_minutes 变换"""
        formatter = DataFormatter([])
        result = formatter._apply_transform(600, "time_minutes", {}, {})
        assert result == "10"

    def test_transform_time_seconds(self) -> None:
        """测试 time_seconds 变换"""
        formatter = DataFormatter([])
        result = formatter._apply_transform(630, "time_seconds", {}, {})
        assert result == "30"

    def test_transform_signed_int(self) -> None:
        """测试 signed_int 变换"""
        formatter = DataFormatter([])
        result = formatter._apply_transform(1500, "signed_int", {}, {})
        assert result == "+1500"

    def test_transform_player_names(self) -> None:
        """测试 player_names 变换"""
        formatter = DataFormatter([])
        player_map: Dict[str, str] = {"acc1": "Juggernaut", "acc2": "Pudge"}
        field_def: Dict[str, Any] = {"max_items": 6}
        result = formatter._apply_transform(
            ["acc1", "acc2", "acc3"],
            "player_names",
            player_map,
            field_def,
        )
        assert "Juggernaut" in result
        assert "Pudge" in result

    def test_transform_none(self) -> None:
        """测试无变换时返回字符串"""
        formatter = DataFormatter([])
        result = formatter._apply_transform(42, None, {}, {})
        assert result == "42"

    def test_transform_none_value(self) -> None:
        """测试值为 None 时返回空字符串"""
        formatter = DataFormatter([])
        result = formatter._apply_transform(None, "time_minutes", {}, {})
        assert result == ""
