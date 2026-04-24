"""pytest 配置和共享 fixtures"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, MagicMock

# 确保能导入模块
import sys
# 添加项目根目录到 sys.path，使模块导入能正常工作
# 这样 cache_manager.py 中的 "from core.config import" 才能找到模块
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 直接导入模块
from core.config import AgentConfig, MatchupConfig, CacheConfig, RateLimitConfig
from cache.cache_manager import CacheManager


@pytest.fixture
def temp_dir():
    """创建临时目录用于测试"""
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def cache_config():
    """缓存配置 fixture"""
    return CacheConfig(
        enabled=True,
        cache_dir="cache",
        ttl_hours=24,
        max_size_mb=100,
        max_items=1000,
        enable_memory_cache=True
    )


@pytest.fixture
def matchup_config():
    """克制分析配置 fixture"""
    return MatchupConfig(
        min_games_threshold=100,
        min_winrate_threshold=0.52,
        score_weight=100.0,
        synergy_weight=50.0
    )


@pytest.fixture
def rate_limit_config():
    """速率限制配置 fixture"""
    return RateLimitConfig(
        delay_seconds=1.0,
        timeout_seconds=10,
        max_retries=3
    )


@pytest.fixture
def agent_config(cache_config, matchup_config, rate_limit_config):
    """Agent 配置 fixture"""
    return AgentConfig(
        api_key=None,
        rate_limit=rate_limit_config,
        cache=cache_config,
        matchup=matchup_config,
        top_n_default=3
    )


@pytest.fixture
def cache_manager(temp_dir):
    """缓存管理器 fixture"""
    return CacheManager(
        cache_dir=temp_dir,
        ttl_hours=24,
        max_size_mb=100,
        max_items=1000,
        enable_memory_cache=True
    )


@pytest.fixture
def mock_api_response():
    """模拟 API 响应 fixture"""
    return {
        "heroes": [
            {"id": 1, "name": "npc_dota_hero_antimage", "localized_name": "Anti-Mage"},
            {"id": 2, "name": "npc_dota_hero_axe", "localized_name": "Axe"},
            {"id": 5, "name": "npc_dota_hero_crystal_maiden", "localized_name": "Crystal Maiden"},
            {"id": 10, "name": "npc_dota_hero_pudge", "localized_name": "Pudge"},
        ],
        "matchups": [
            {
                "hero_id": 2,
                "games_played": 150,
                "wins": 80,
            },
            {
                "hero_id": 5,
                "games_played": 200,
                "wins": 90,
            }
        ],
        "items": {
            "item_blink": 1250,
            "item_black_king_bar": 980,
            "item_ultimate_scepter": 750,
        }
    }


@pytest.fixture
def mock_hero_data():
    """模拟英雄数据 fixture"""
    return [
        {"id": 1, "name": "npc_dota_hero_antimage", "localized_name": "Anti-Mage"},
        {"id": 2, "name": "npc_dota_hero_axe", "localized_name": "Axe"},
        {"id": 5, "name": "npc_dota_hero_crystal_maiden", "localized_name": "Crystal Maiden"},
        {"id": 10, "name": "npc_dota_hero_pudge", "localized_name": "Pudge"},
        {"id": 15, "name": "npc_dota_hero_phantom_assassin", "localized_name": "Phantom Assassin"},
    ]


@pytest.fixture
def mock_matchup_data():
    """模拟克制数据 fixture"""
    return [
        {
            "hero_id": 2,
            "games_played": 150,
            "wins": 80,
        },
        {
            "hero_id": 5,
            "games_played": 200,
            "wins": 90,
        },
        {
            "hero_id": 10,
            "games_played": 180,
            "wins": 70,
        }
    ]


@pytest.fixture
def mock_item_data():
    """模拟物品数据 fixture"""
    return {
        "start_game_items": {
            1: 500,
            2: 450,
            3: 400,
        },
        "early_game_items": {
            4: 800,
            5: 600,
            6: 500,
        },
        "mid_game_items": {
            7: 1250,
            8: 980,
            9: 850,
        },
        "late_game_items": {
            10: 750,
            11: 300,
            12: 600,
        }
    }
