"""Stats-related MCP tools — async versions.

Provides tools for querying public matches, scenarios (item timings,
lane roles, misc), MMR distribution, records, and constants via the
OpenDota API.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from dota_helper.mcp_server.server import mcp

logger = logging.getLogger(__name__)

from dota_helper.mcp_server.helpers.opendota import AsyncOpenDotaClient
from dota_helper.mcp_server.helpers.hero_names import get_cn_name, get_rank_display, get_rank_bin_display


# ---------------------------------------------------------------------------
# Constants resource whitelist (mirrors dota2_fastmcp.py)
# ---------------------------------------------------------------------------

CONSTANT_RESOURCES: List[str] = [
    "abilities",
    "ability_ids",
    "aghs_desc",
    "ancients",
    "chat_wheel",
    "cluster",
    "countries",
    "game_mode",
    "hero_abilities",
    "hero_lore",
    "heroes",
    "item_colors",
    "item_ids",
    "items",
    "lobby_type",
    "neutral_abilities",
    "order_types",
    "patch",
    "patchnotes",
    "permanent_buffs",
    "player_colors",
    "region",
    "skillshots",
    "xp_level",
]


async def _build_hero_map() -> Dict[int, str]:
    """Build a hero_id -> localized_name mapping from the API."""
    client = AsyncOpenDotaClient.get_instance()
    heroes = await client.get_heroes()
    return {h["id"]: h.get("localized_name", f"Hero {h['id']}") for h in heroes}


async def _load_constants_resource(resource: str) -> Tuple[Optional[Any], str, str, Optional[str]]:
    """Load a constants resource, preferring a local cache file.

    Returns:
        A tuple of (data, source, output_path, error).
    """
    output_dir = "api_samples"
    filename = f"constants_{resource}.json"
    output_path = os.path.join(output_dir, filename)

    if os.path.exists(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info("_load_constants_resource: cache hit for resource=%s", resource)
            return data, "local", output_path, None
        except Exception as exc:
            logger.warning("_load_constants_resource: cache read failed for resource=%s: %s", resource, exc)
            return None, "local", output_path, f"读取失败: {exc}"

    logger.info("_load_constants_resource: cache miss for resource=%s, fetching from API", resource)
    client = AsyncOpenDotaClient.get_instance()
    data = await client.get(f"constants/{resource}")
    if isinstance(data, dict) and "error" in data:
        logger.warning("_load_constants_resource: API returned error for resource=%s: %s", resource, data.get("error"))
        return None, "api", output_path, data.get("error")

    try:
        os.makedirs(output_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("_load_constants_resource: cache write success for resource=%s", resource)
    except Exception as exc:
        logger.warning("_load_constants_resource: cache write failed for resource=%s: %s", resource, exc)

    return data, "api", output_path, None


@mcp.tool()
async def get_public_matches(min_rank: int = 70, limit: int = 20) -> str:
    """
    获取最近的公开比赛列表

    Args:
        min_rank: 最低段位等级，默认70（神话），范围10-85
        limit: 返回的比赛数量，默认20

    Returns:
        公开比赛列表，包括比赛ID、段位、时长等
    """
    logger.info("get_public_matches called with: min_rank=%s, limit=%s", min_rank, limit)

    client = AsyncOpenDotaClient.get_instance()
    data = await client.get("publicMatches", params={"min_rank": min_rank})

    if isinstance(data, dict) and "error" in data:
        logger.warning("get_public_matches: API returned error: %s", data["error"])
        return f"❌ API 错误: {data['error']}"

    if not isinstance(data, list):
        logger.warning("get_public_matches: unexpected data type=%s", type(data).__name__)
        return "❌ 获取公开比赛失败"

    logger.info("get_public_matches: fetched data successfully")

    matches = data[:limit]

    lines = [
        f"# 🎮 公开比赛 (段位 ≥ {min_rank})",
        "",
        "| Match ID | 段位 | 时长 | 天辉英雄 | 夜魇英雄 |",
        "|----------|------|------|----------|----------|",
    ]

    for m in matches:
        match_id = m.get("match_id", "N/A")
        rank = m.get("avg_rank_tier", "N/A")
        rank_text = get_rank_display(rank) if rank not in ("N/A", None, "") else None
        rank_display = f"{rank_text}（{rank}）" if rank_text else str(rank)
        duration = m.get("duration", 0)
        minutes = duration // 60

        radiant = m.get("radiant_team", "")
        dire = m.get("dire_team", "")

        lines.append(f"| {match_id} | {rank_display} | {minutes}分 | {radiant[:20]} | {dire[:20]} |")

    logger.info("get_public_matches: completed")
    return "\n".join(lines)


@mcp.tool()
async def get_scenarios_item_timings(
    item: Optional[str] = None,
    hero_id: Optional[int] = None,
    limit: int = 20,
) -> str:
    """
    获取英雄特定装备时机的胜率统计

    Args:
        item: 物品名（如 spirit_vessel）
        hero_id: 英雄ID
        limit: 返回数量，默认20

    Returns:
        装备时机统计列表
    """
    logger.info("get_scenarios_item_timings called with: item=%s, hero_id=%s, limit=%s", item, hero_id, limit)

    params: Dict[str, Any] = {}
    if item:
        params["item"] = item
    if hero_id is not None:
        params["hero_id"] = hero_id

    client = AsyncOpenDotaClient.get_instance()
    data = await client.get("scenarios/itemTimings", params=params or None)

    if isinstance(data, dict) and "error" in data:
        logger.warning("get_scenarios_item_timings: API returned error: %s", data["error"])
        return f"❌ API 错误: {data['error']}"

    if not isinstance(data, list):
        logger.warning("get_scenarios_item_timings: unexpected data type=%s", type(data).__name__)
        return "❌ 获取装备时机数据失败"

    logger.info("get_scenarios_item_timings: fetched data successfully")

    records = data[:limit]
    hero_map = await _build_hero_map()

    lines = [
        "# ⏱️ 装备时机胜率",
        "",
        "| 英雄 | 装备 | 时间 | 场次 | 胜场 | 胜率 |",
        "|------|------|------|------|------|------|",
    ]

    def _to_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    for row in records:
        hid = int(row.get("hero_id", 0) or 0)
        hero_en = hero_map.get(hid, f"Hero {hid}")
        hero_cn = get_cn_name(hero_en)
        item_name = row.get("item", "N/A")
        time_val = _to_int(row.get("time", 0))
        minutes, seconds = divmod(time_val, 60)
        time_label = f"{minutes}:{seconds:02d}"
        games = _to_int(row.get("games", 0))
        wins = _to_int(row.get("wins", 0))
        win_rate = f"{(wins / games * 100):.1f}%" if games > 0 else "N/A"
        lines.append(f"| {hero_cn} | {item_name} | {time_label} | {games} | {wins} | {win_rate} |")

    logger.info("get_scenarios_item_timings: completed")
    return "\n".join(lines)


@mcp.tool()
async def get_scenarios_lane_roles(
    lane_role: Optional[int] = None,
    hero_id: Optional[int] = None,
    limit: int = 20,
) -> str:
    """
    获取英雄在不同分路角色的胜率统计

    Args:
        lane_role: 分路角色 1-4（安全/中/劣/打野）
        hero_id: 英雄ID
        limit: 返回数量，默认20

    Returns:
        分路角色统计列表
    """
    logger.info("get_scenarios_lane_roles called with: lane_role=%s, hero_id=%s, limit=%s", lane_role, hero_id, limit)

    params: Dict[str, Any] = {}
    if lane_role is not None:
        params["lane_role"] = lane_role
    if hero_id is not None:
        params["hero_id"] = hero_id

    client = AsyncOpenDotaClient.get_instance()
    data = await client.get("scenarios/laneRoles", params=params or None)

    if isinstance(data, dict) and "error" in data:
        logger.warning("get_scenarios_lane_roles: API returned error: %s", data["error"])
        return f"❌ API 错误: {data['error']}"

    if not isinstance(data, list):
        logger.warning("get_scenarios_lane_roles: unexpected data type=%s", type(data).__name__)
        return "❌ 获取分路角色数据失败"

    logger.info("get_scenarios_lane_roles: fetched data successfully")

    records = data[:limit]
    hero_map = await _build_hero_map()
    lane_map = {1: "安全路", 2: "中路", 3: "劣势路", 4: "打野"}

    lines = [
        "# 🛣️ 分路角色胜率",
        "",
        "| 英雄 | 分路 | 时长上限 | 场次 | 胜场 | 胜率 |",
        "|------|------|----------|------|------|------|",
    ]

    def _to_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    for row in records:
        hid = int(row.get("hero_id", 0) or 0)
        hero_en = hero_map.get(hid, f"Hero {hid}")
        hero_cn = get_cn_name(hero_en)
        role_val = _to_int(row.get("lane_role", 0))
        lane_label = lane_map.get(role_val, str(role_val))
        time_val = _to_int(row.get("time", 0))
        minutes, seconds = divmod(time_val, 60)
        time_label = f"{minutes}:{seconds:02d}"
        games = _to_int(row.get("games", 0))
        wins = _to_int(row.get("wins", 0))
        win_rate = f"{(wins / games * 100):.1f}%" if games > 0 else "N/A"
        lines.append(f"| {hero_cn} | {lane_label} | {time_label} | {games} | {wins} | {win_rate} |")

    logger.info("get_scenarios_lane_roles: completed")
    return "\n".join(lines)


@mcp.tool()
async def get_scenarios_misc(scenario: Optional[str] = None, limit: int = 20) -> str:
    """
    获取杂项场景胜率统计

    Args:
        scenario: 场景名称
        limit: 返回数量，默认20

    Returns:
        场景统计列表
    """
    logger.info("get_scenarios_misc called with: scenario=%s, limit=%s", scenario, limit)

    params: Dict[str, Any] = {}
    if scenario:
        params["scenario"] = scenario

    client = AsyncOpenDotaClient.get_instance()
    data = await client.get("scenarios/misc", params=params or None)

    if isinstance(data, dict) and "error" in data:
        logger.warning("get_scenarios_misc: API returned error: %s", data["error"])
        return f"❌ API 错误: {data['error']}"

    if not isinstance(data, list):
        logger.warning("get_scenarios_misc: unexpected data type=%s", type(data).__name__)
        return "❌ 获取场景统计失败"

    logger.info("get_scenarios_misc: fetched data successfully")

    records = data[:limit]

    lines = [
        "# 🧩 场景胜率统计",
        "",
        "| 场景 | 阵营 | 区域 | 场次 | 胜场 | 胜率 |",
        "|------|------|------|------|------|------|",
    ]

    def _to_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    for row in records:
        scenario_name = row.get("scenario", "N/A")
        is_radiant = row.get("is_radiant")
        side = "天辉" if is_radiant else "夜魇"
        if is_radiant is None:
            side = "未知"
        region = row.get("region", "N/A")
        games = _to_int(row.get("games", 0))
        wins = _to_int(row.get("wins", 0))
        win_rate = f"{(wins / games * 100):.1f}%" if games > 0 else "N/A"
        lines.append(f"| {scenario_name} | {side} | {region} | {games} | {wins} | {win_rate} |")

    logger.info("get_scenarios_misc: completed")
    return "\n".join(lines)


@mcp.tool()
async def get_mmr_distribution() -> str:
    """
    获取全服 MMR 分布数据

    Returns:
        MMR 分布统计，包括各段位的玩家数量和百分比
    """
    logger.info("get_mmr_distribution called")

    client = AsyncOpenDotaClient.get_instance()
    data = await client.get("distributions")

    if isinstance(data, dict) and "error" in data:
        logger.warning("get_mmr_distribution: API returned error: %s", data["error"])
        return f"❌ API 错误: {data['error']}"

    logger.info("get_mmr_distribution: fetched data successfully")

    ranks = data.get("ranks", {})
    rows = ranks.get("rows", [])

    lines = [
        "# 📊 段位分布",
        "",
        "| 段位 | 玩家数 | 累计百分比 |",
        "|------|--------|------------|",
    ]

    for r in rows[:20]:
        bin_name = r.get("bin_name", "N/A")
        bin_id = r.get("bin")
        bin_display = get_rank_bin_display(bin_name, bin_id)
        count = r.get("count", 0)
        cum_sum = r.get("cumulative_sum", 0)

        lines.append(f"| {bin_display} | {count:,} | {cum_sum:.2f}% |")

    logger.info("get_mmr_distribution: completed")
    return "\n".join(lines)


@mcp.tool()
async def get_records(field: str, limit: int = 20) -> str:
    """
    获取指定字段的最高记录

    Args:
        field: 记录字段名（例如 kills, gpm, xpm, hero_damage 等）
        limit: 返回数量，默认20

    Returns:
        记录列表，包括比赛ID、英雄、分数和时间
    """
    logger.info("get_records called with: field=%s, limit=%s", field, limit)

    field = str(field or "").strip()
    if not field:
        return "❌ field 不能为空"

    client = AsyncOpenDotaClient.get_instance()
    data = await client.get(f"records/{field}")

    if isinstance(data, dict) and "error" in data:
        logger.warning("get_records: API returned error: %s", data["error"])
        return f"❌ API 错误: {data['error']}"

    if not isinstance(data, list):
        logger.warning("get_records: unexpected data type=%s", type(data).__name__)
        return "❌ 获取记录数据失败"

    logger.info("get_records: fetched data successfully")

    records = data[:limit]
    hero_map = await _build_hero_map()

    lines = [
        f"# 🏅 记录排行 - {field}",
        "",
        "| Match ID | 时间 | 英雄 | 记录值 |",
        "|----------|------|------|--------|",
    ]

    for r in records:
        match_id = r.get("match_id", "N/A")
        start_time = r.get("start_time", 0)
        try:
            time_str = time.strftime("%Y-%m-%d", time.gmtime(int(start_time)))
        except (TypeError, ValueError, OSError):
            time_str = "N/A"
        hero_id = int(r.get("hero_id", 0) or 0)
        hero_en = hero_map.get(hero_id, f"Hero {hero_id}")
        hero_cn = get_cn_name(hero_en)
        score = r.get("score", 0)
        lines.append(f"| {match_id} | {time_str} | {hero_cn} | {score} |")

    logger.info("get_records: completed")
    return "\n".join(lines)


@mcp.tool()
async def get_constants(resource: str) -> str:
    """
    获取 OpenDota constants 静态数据（优先读取本地缓存）

    Args:
        resource: constants 资源名（如 heroes, items, abilities）

    Returns:
        constants 数据（JSON），包含来源与路径
    """
    logger.info("get_constants called with: resource=%s", resource)

    resource = str(resource or "").strip()
    if not resource:
        return "❌ resource 不能为空"

    resource = resource.replace(".json", "").strip().lower()
    if resource in ("list", "all", "catalog"):
        return json.dumps(
            {"resources": CONSTANT_RESOURCES},
            ensure_ascii=False,
            indent=2,
        )

    if resource not in CONSTANT_RESOURCES:
        return (
            "❌ 未支持的 constants 资源。可用资源："
            + ", ".join(CONSTANT_RESOURCES)
        )

    data, source, output_path, error = await _load_constants_resource(resource)
    if error:
        return f"❌ API 错误: {error}"
    result = {"source": source, "path": output_path, "data": data}
    logger.info("get_constants: completed")
    return json.dumps(result, ensure_ascii=False, indent=2)
