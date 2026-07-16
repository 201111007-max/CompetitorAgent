"""测试配置和 fixtures"""
import sys
from pathlib import Path

# 关键：将 post_match_review 目录本身添加到 sys.path
# 这样 post_match_review 会成为顶级包，避免加载 DotaHelperAgent/__init__.py
_pmr_root = Path(__file__).parent.parent
if str(_pmr_root) not in sys.path:
    sys.path.insert(0, str(_pmr_root))

import json
from typing import Any, Dict

import pytest


@pytest.fixture
def package_root() -> Path:
    """指向 post_match_review/ 自身"""
    return Path(__file__).parent.parent


@pytest.fixture
def sample_match_data() -> Dict[str, Any]:
    """样本 OpenDota API 响应数据"""
    return {
        "match_id": 8893253595,
        "duration": 1800,  # 30 分钟
        "radiant_win": True,
        "radiant_score": 35,
        "dire_score": 20,
        "game_mode": 22,
        "players": [
            {
                "account_id": 100000000 + i,
                "hero_id": 8,
                "hero_name": "Juggernaut",
                "kills": 10,
                "deaths": 2,
                "assists": 15,
                "last_hits": 250,
                "denies": 15,
                "gold_per_min": 650,
                "xp_per_min": 700,
                "hero_damage": 25000,
                "tower_damage": 8000,
                "isRadiant": i < 5,
                "level": 20,
                "gold": 3500,
                "lane": 1 if i < 5 else 3,
                "lh_t": [0, 5, 12, 20, 30, 42, 55, 70, 88, 105, 125],
                "denies_t": [0, 1, 2, 3, 5, 7, 9, 11, 13, 14, 15],
                "gold_t": [0, 500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000],
                "xp_t": [0, 400, 800, 1200, 1600, 2000, 2400, 2800, 3200, 3600, 4000],
                "net_worth_t": [0, 600, 1200, 1800, 2400, 3000, 3600, 4200, 4800, 5400, 6000],
                "purchase_log": [
                    {"time": 120, "key": "boots"},
                    {"time": 450, "key": "bfury"},
                ],
            }
            for i in range(10)
        ],
        "picks_bans": [
            {"is_pick": True, "hero_id": 8, "team": 0, "order": 0},
            {"is_pick": True, "hero_id": 44, "team": 1, "order": 1},
            {"is_pick": False, "hero_id": 14, "team": 0, "order": 2},
        ],
        "teamfights": [
            {
                "start": 600,
                "end": 650,
                "deaths": 5,
                "players": [
                    {"account_id": 123456789, "participation": True},
                    {"account_id": 987654321, "participation": True},
                ],
                "radiant_gold_delta": 2000,
                "dire_gold_delta": -2000,
            }
        ],
    }


@pytest.fixture
def match_fixture_file(tmp_path: Path, sample_match_data: Dict[str, Any]) -> Path:
    """创建临时 fixture 文件"""
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    fixture_file = fixture_dir / "match_8893253595.json"
    with open(fixture_file, "w", encoding="utf-8") as f:
        json.dump(sample_match_data, f)
    return fixture_file
