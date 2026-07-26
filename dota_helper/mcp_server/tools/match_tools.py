"""Async match-related MCP tools for Dota 2 Helper Agent.

Converted from sync tools in dota2_fastmcp.py (lines 2484-2957, 3377-3429).
All data fetching is performed via AsyncOpenDotaClient.
"""
import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from dota_helper.mcp_server.server import mcp
from dota_helper.mcp_server.helpers.opendota import AsyncOpenDotaClient
from dota_helper.mcp_server.helpers.hero_names import get_cn_name
from dota_helper.mcp_server.helpers.map_config import format_time_mmss


# ---------------------------------------------------------------------------
# Module-level helper functions (extracted from nested helpers in
# get_match_details)
# ---------------------------------------------------------------------------


def _count_bits(value: Any) -> Optional[int]:
    """Count the number of set bits in *value*."""
    try:
        return bin(int(value)).count("1")
    except (TypeError, ValueError):
        logger.debug("_count_bits: failed to count bits for value=%s", value)
        return None


def _skill_display(value: Any) -> str:
    """Format a skill bracket value into a display string."""
    mapping = {1: "Normal", 2: "High", 3: "Very High"}
    try:
        value_int = int(value)
    except (TypeError, ValueError):
        logger.debug("_skill_display: failed to convert value=%s", value)
        return "N/A" if value is None else str(value)
    return mapping.get(value_int, str(value_int))


def _series_display(value: Any) -> str:
    """Format a series type value into a display string."""
    mapping = {0: "Single Game", 1: "Bo1", 2: "Bo3", 3: "Bo5"}
    try:
        value_int = int(value)
    except (TypeError, ValueError):
        logger.debug("_series_display: failed to convert value=%s", value)
        return "N/A" if value is None else str(value)
    return mapping.get(value_int, str(value_int))


def _sum_int(players: List[Dict[str, Any]], field: str) -> int:
    """Sum an integer field across a list of player dicts."""
    total = 0
    for p in players:
        try:
            total += int(p.get(field) or 0)
        except (TypeError, ValueError):
            logger.debug("_sum_int: skipping non-integer value for field=%s", field)
            continue
    return total


def _sum_float(players: List[Dict[str, Any]], field: str) -> float:
    """Sum a float field across a list of player dicts."""
    total = 0.0
    for p in players:
        try:
            total += float(p.get(field) or 0)
        except (TypeError, ValueError):
            logger.debug("_sum_float: skipping non-float value for field=%s", field)
            continue
    return total


def _is_radiant(p: Dict[str, Any]) -> bool:
    """Determine if a player is on the Radiant side."""
    if p.get("isRadiant") is not None:
        return bool(p.get("isRadiant"))
    return p.get("player_slot", 128) < 128


def _format_items_from_ids(
    item_ids: List[Any],
    items_map: Dict[int, Dict[str, Any]],
    client: AsyncOpenDotaClient,
) -> str:
    """Format a list of item IDs into a slash-separated name string."""
    names: List[str] = []
    for item_id in item_ids:
        entry = client.build_item_entry(item_id, items_map)
        if entry:
            item_name = entry.get("name") or str(entry.get("id"))
        else:
            item_name = "-"
        names.append(str(item_name))
    return " / ".join(names)


def _format_items(
    p: Dict[str, Any],
    items_map: Dict[int, Dict[str, Any]],
    client: AsyncOpenDotaClient,
) -> str:
    """Format the 6 inventory item slots of a player."""
    return _format_items_from_ids(
        [p.get(f"item_{slot}") for slot in range(6)], items_map, client
    )


def _format_backpack(
    p: Dict[str, Any],
    items_map: Dict[int, Dict[str, Any]],
    client: AsyncOpenDotaClient,
) -> str:
    """Format the 3 backpack slots of a player."""
    backpack_ids = [p.get(f"backpack_{slot}") for slot in range(3)]
    if not any(backpack_ids):
        return "-"
    return _format_items_from_ids(backpack_ids, items_map, client)


def _format_neutral(
    p: Dict[str, Any],
    items_map: Dict[int, Dict[str, Any]],
    client: AsyncOpenDotaClient,
) -> str:
    """Format the neutral item of a player."""
    neutral_id = p.get("item_neutral") if p.get("item_neutral") is not None else p.get("item_neutral_id")
    if neutral_id is None:
        return "-"
    entry = client.build_item_entry(neutral_id, items_map)
    if entry:
        return str(entry.get("name") or entry.get("id"))
    return str(neutral_id)


def _lookup_const_name(
    resource: str,
    key: Any,
    constants_data: Any,
) -> str:
    """Look up a display name from a constants resource dict/list.

    Args:
        resource: The constants resource name (for debugging).
        key: The key to look up.
        constants_data: The parsed JSON data from the constants endpoint.

    Returns:
        A human-readable name string, or the raw key if not found.
    """
    if key is None:
        return "N/A"
    key_str = str(key)
    if isinstance(constants_data, dict):
        entry = constants_data.get(key_str)
        if entry is None:
            try:
                entry = constants_data.get(int(key))
            except (TypeError, ValueError):
                logger.debug("_lookup_const_name: failed int conversion for key=%s in resource=%s", key, resource)
                entry = None
        if isinstance(entry, dict):
            for field in ("name", "localized_name", "desc", "date"):
                if entry.get(field):
                    return str(entry.get(field))
            if entry.get("id") is not None:
                return str(entry.get("id"))
        if isinstance(entry, str):
            return entry
    if isinstance(constants_data, list):
        for item in constants_data:
            if not isinstance(item, dict):
                continue
            if str(item.get("id")) == key_str or str(item.get("patch")) == key_str:
                for field in ("name", "localized_name", "desc", "date"):
                    if item.get(field):
                        return str(item.get(field))
    return str(key)


def _team_summary(
    title: str,
    team_players: List[Dict[str, Any]],
) -> List[str]:
    """Build a summary line for one team's players."""
    if not team_players:
        return []
    kills = _sum_int(team_players, "kills")
    deaths = _sum_int(team_players, "deaths")
    assists = _sum_int(team_players, "assists")
    net_worth = _sum_int(team_players, "net_worth")
    hero_damage = _sum_int(team_players, "hero_damage")
    tower_damage = _sum_int(team_players, "tower_damage")
    hero_healing = _sum_int(team_players, "hero_healing")
    gpm = _sum_int(team_players, "gold_per_min")
    xpm = _sum_int(team_players, "xp_per_min")
    last_hits = _sum_int(team_players, "last_hits")
    denies = _sum_int(team_players, "denies")
    obs = _sum_int(team_players, "obs_placed")
    sen = _sum_int(team_players, "sen_placed")
    stuns = _sum_float(team_players, "stuns")
    return [
        f"- {title}: K/D/A={kills}/{deaths}/{assists}, 净资产={net_worth}, GPM={gpm}, XPM={xpm}, LH/DN={last_hits}/{denies}",
        f"  伤害(英雄/塔/治疗)={hero_damage}/{tower_damage}/{hero_healing}, 视野(真/假)={obs}/{sen}, 控制时长={stuns:.1f}s",
    ]


def _append_player_table(
    lines: List[str],
    title: str,
    team_players: List[Dict[str, Any]],
    hero_map: Dict[int, str],
    items_map: Dict[int, Dict[str, Any]],
    client: AsyncOpenDotaClient,
) -> None:
    """Append a Markdown table of player details to *lines*."""
    if not team_players:
        return
    lines.append("")
    lines.append(title)
    lines.append("| 英雄 | 选手 | 选手ID | K/D/A | 等级 | LH/DN | GPM/XPM | 净资产 | 伤害(英雄/塔/治疗) | 视野(真/假) | 位置 | 装备 | 背包 | 中立 |")
    lines.append("|------|------|--------|-------|------|------|---------|-------|------------------|-----------|------|------|------|------|")
    for p in team_players:
        hero_en = hero_map.get(p.get("hero_id"), f"Hero {p.get('hero_id')}")
        hero_cn = get_cn_name(hero_en)
        player_name = p.get("name") or p.get("personaname") or "Unknown"
        player_id = p.get("account_id") if p.get("account_id") is not None else "Unknown"
        kda = f"{p.get('kills', 0)}/{p.get('deaths', 0)}/{p.get('assists', 0)}"
        level = p.get("level", 0)
        lh_dn = f"{p.get('last_hits', 0)}/{p.get('denies', 0)}"
        gpm_xpm = f"{p.get('gold_per_min', 0)}/{p.get('xp_per_min', 0)}"
        net_worth = p.get("net_worth", 0)
        damage_block = f"{p.get('hero_damage', 0)}/{p.get('tower_damage', 0)}/{p.get('hero_healing', 0)}"
        wards_block = f"{p.get('obs_placed', 0)}/{p.get('sen_placed', 0)}"
        lane = p.get("lane")
        lane_role = p.get("lane_role")
        lane_display = "-"
        if lane is not None or lane_role is not None:
            lane_display = f"{lane if lane is not None else '-'} / {lane_role if lane_role is not None else '-'}"
        items_display = _format_items(p, items_map, client)
        backpack_display = _format_backpack(p, items_map, client)
        neutral_display = _format_neutral(p, items_map, client)
        lines.append(
            f"| {hero_cn} | {player_name} | {player_id} | {kda} | {level} | {lh_dn} | {gpm_xpm} | {net_worth} | "
            f"{damage_block} | {wards_block} | {lane_display} | {items_display} | {backpack_display} | {neutral_display} |"
        )


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_match_details(match_id: int) -> str:
    """
    获取 Dota 2 比赛信息摘要（matches/{match_id}）

    Args:
        match_id: Dota 2 比赛ID，例如 8650430843

    Returns:
        比赛摘要 + 双方阵容/数据概览（不包含原始 JSON）
    """
    logger.info("get_match_details called with: match_id=%s", match_id)
    client = AsyncOpenDotaClient.get_instance()
    data = await client.get(f"matches/{match_id}")

    if isinstance(data, dict) and "error" in data:
        logger.warning("get_match_details: API returned error for match_id=%s: %s", match_id, data.get("error"))
        return f"❌ API 错误: {data['error']}"

    if not isinstance(data, dict):
        logger.warning("get_match_details: unexpected data type=%s for match_id=%s", type(data).__name__, match_id)
        return "❌ 获取比赛详情失败"

    logger.info("get_match_details: API call succeeded, data type=%s", type(data).__name__)

    hero_map = await client.get_cached_hero_map()
    item_map = await client.get_cached_items_map()

    # Pre-fetch constants resources needed for lookup
    game_mode_data = await client.get_cached_constants("game_mode")
    lobby_type_data = await client.get_cached_constants("lobby_type")
    region_data = await client.get_cached_constants("region")
    patch_data = await client.get_cached_constants("patch")

    duration = int(data.get("duration") or 0)
    minutes, seconds = divmod(duration, 60)
    radiant_win = data.get("radiant_win")
    if radiant_win is True:
        winner = "天辉 (Radiant)"
    elif radiant_win is False:
        winner = "夜魇 (Dire)"
    else:
        winner = "未知"

    start_time = data.get("start_time")
    start_time_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(int(start_time))) if start_time else "N/A"
    first_blood_time = data.get("first_blood_time")
    first_blood_str = format_time_mmss(int(first_blood_time)) if first_blood_time is not None else "N/A"

    game_mode = data.get("game_mode")
    lobby_type = data.get("lobby_type")
    region = data.get("region")
    patch = data.get("patch")
    skill = data.get("skill")

    game_mode_name = _lookup_const_name("game_mode", game_mode, game_mode_data)
    lobby_name = _lookup_const_name("lobby_type", lobby_type, lobby_type_data)
    region_name = _lookup_const_name("region", region, region_data)
    patch_name = _lookup_const_name("patch", patch, patch_data)

    radiant_team = data.get("radiant_team") or {}
    dire_team = data.get("dire_team") or {}
    league = data.get("league") or {}

    tower_radiant = data.get("tower_status_radiant")
    tower_dire = data.get("tower_status_dire")
    barracks_radiant = data.get("barracks_status_radiant")
    barracks_dire = data.get("barracks_status_dire")

    tower_radiant_alive = _count_bits(tower_radiant)
    tower_dire_alive = _count_bits(tower_dire)
    barracks_radiant_alive = _count_bits(barracks_radiant)
    barracks_dire_alive = _count_bits(barracks_dire)

    lines: List[str] = [
        f"# 比赛详情 - Match ID: {data.get('match_id')}",
        "",
        "## 基本信息",
        f"- 时间: {start_time_str}",
        f"- 时长: {minutes}分{seconds}秒 ({duration}s)",
        f"- 获胜方: {winner}",
        f"- 比分: 天辉 {data.get('radiant_score', 0)} - {data.get('dire_score', 0)} 夜魇",
        f"- 首杀时间: {first_blood_str}",
        f"- 模式: {game_mode_name} ({game_mode})",
        f"- 房间: {lobby_name} ({lobby_type})",
        f"- 地区: {region_name} ({region})",
        f"- 段位: {_skill_display(skill)}",
        f"- 联赛: {league.get('name') or data.get('leagueid', 'N/A')} (ID: {data.get('leagueid', 'N/A')})",
        f"- 系列赛: {_series_display(data.get('series_type'))} (series_id: {data.get('series_id', 'N/A')})",
        f"- Patch: {patch_name} ({patch})",
        f"- Cluster: {data.get('cluster', 'N/A')}",
        f"- 人类玩家数: {data.get('human_players', 'N/A')}",
    ]

    if data.get("replay_url"):
        lines.append(f"- 回放: {data.get('replay_url')}")

    if radiant_team or dire_team:
        lines.append("")
        lines.append("## 队伍信息")
        if radiant_team:
            lines.append(f"- 天辉: {radiant_team.get('name', 'Unknown')} (ID: {radiant_team.get('team_id', 'N/A')})")
        if dire_team:
            lines.append(f"- 夜魇: {dire_team.get('name', 'Unknown')} (ID: {dire_team.get('team_id', 'N/A')})")

    if tower_radiant is not None or tower_dire is not None:
        lines.append("")
        lines.append("## 建筑状态")
        if tower_radiant is not None or tower_dire is not None:
            tr = f"{tower_radiant_alive}/11" if tower_radiant_alive is not None else "N/A"
            td = f"{tower_dire_alive}/11" if tower_dire_alive is not None else "N/A"
            lines.append(f"- 防御塔剩余: 天辉 {tr} (mask {tower_radiant}) / 夜魇 {td} (mask {tower_dire})")
        if barracks_radiant is not None or barracks_dire is not None:
            br = f"{barracks_radiant_alive}/6" if barracks_radiant_alive is not None else "N/A"
            bd = f"{barracks_dire_alive}/6" if barracks_dire_alive is not None else "N/A"
            lines.append(f"- 兵营剩余: 天辉 {br} (mask {barracks_radiant}) / 夜魇 {bd} (mask {barracks_dire})")

    gold_adv = data.get("radiant_gold_adv") or []
    xp_adv = data.get("radiant_xp_adv") or []
    if gold_adv or xp_adv:
        lines.append("")
        lines.append("## 经济/经验走势")
        if gold_adv:
            lines.append(
                f"- 经济优势(天辉视角): 最佳 {max(gold_adv)}, 最差 {min(gold_adv)}, 终局 {gold_adv[-1]}"
            )
        if xp_adv:
            lines.append(
                f"- 经验优势(天辉视角): 最佳 {max(xp_adv)}, 最差 {min(xp_adv)}, 终局 {xp_adv[-1]}"
            )

    players = data.get("players") or []
    if players:
        radiant_players = [p for p in players if _is_radiant(p)]
        dire_players = [p for p in players if not _is_radiant(p)]

        lines.append("")
        lines.append("## 阵营总览")
        lines.extend(_team_summary("天辉", radiant_players))
        lines.extend(_team_summary("夜魇", dire_players))

        _append_player_table(lines, "## 🟦 天辉阵容 (Radiant)", radiant_players, hero_map, item_map, client)
        _append_player_table(lines, "## 🟥 夜魇阵容 (Dire)", dire_players, hero_map, item_map, client)

    picks_bans = data.get("picks_bans") or []
    if picks_bans:
        lines.append("")
        lines.append("## BP 阶段")
        lines.append("| 顺序 | 选择 | 阵营 | 英雄 |")
        lines.append("|------|------|------|------|")
        for entry in picks_bans:
            hero_id = entry.get("hero_id")
            hero_en = hero_map.get(hero_id, f"Hero {hero_id}")
            hero_cn = get_cn_name(hero_en)
            is_pick = entry.get("is_pick")
            pick_label = "Pick" if is_pick else "Ban"
            team_val = entry.get("team")
            if team_val == 0:
                team_label = "天辉"
            elif team_val == 1:
                team_label = "夜魇"
            else:
                team_label = str(team_val)
            lines.append(f"| {entry.get('order', '-')} | {pick_label} | {team_label} | {hero_cn} |")

    objectives = data.get("objectives") or []
    if objectives:
        lines.append("")
        lines.append("## 关键事件统计")
        counts: Dict[str, int] = {}
        for obj in objectives:
            obj_type = obj.get("type") or "unknown"
            counts[obj_type] = counts.get(obj_type, 0) + 1
        sorted_counts = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
        lines.append(", ".join([f"{k}: {v}" for k, v in sorted_counts[:15]]))

    result = "\n".join(lines)
    logger.info("get_match_details: completed for match_id=%s, result_len=%d", match_id, len(result))
    return result


@mcp.tool()
async def get_match_items(match_id: int) -> str:
    """
    提取比赛中所有玩家的购买记录（基于 purchase_log / purchase_time）

    Args:
        match_id: Dota 2 比赛ID，例如 8650430843

    Returns:
        所有玩家的购买记录(JSON)，仅保留非消耗品装备
    """
    logger.info("get_match_items called with: match_id=%s", match_id)
    client = AsyncOpenDotaClient.get_instance()
    match_data = await client.get(f"matches/{match_id}")

    if isinstance(match_data, dict) and "error" in match_data:
        logger.warning("get_match_items: API returned error for match_id=%s: %s", match_id, match_data.get("error"))
        return f"❌ API 错误: {match_data['error']}"

    players = match_data.get("players") if isinstance(match_data, dict) else None
    if not players:
        logger.warning("get_match_items: unexpected data type=%s for match_id=%s", type(match_data).__name__, match_id)
        return f"❌ 无法获取比赛 {match_id} 的玩家数据"

    logger.info("get_match_items: API call succeeded, data type=%s", type(match_data).__name__)

    hero_map = await client.get_cached_hero_map()
    item_map = await client.get_cached_items_map()

    key_map: Dict[str, Dict[str, Any]] = {}
    consumable_keys: set = set()
    for item_id, info in item_map.items():
        key = info.get("key")
        if not key:
            continue
        entry = {
            "id": item_id,
            "key": key,
            "name": info.get("name"),
            "qual": info.get("qual"),
        }
        key_map[str(key)] = entry
        if str(info.get("qual")) == "consumable":
            consumable_keys.add(str(key))

    def _is_non_consumable(item_key: Any) -> bool:
        return str(item_key) not in consumable_keys

    def _build_purchase_entry(item_key: Any, time_val: Any) -> Dict[str, Any]:
        info = key_map.get(str(item_key))
        try:
            time_int = int(time_val)
        except (TypeError, ValueError):
            logger.debug("_build_purchase_entry: failed to convert time_val=%s", time_val)
            time_int = None
        return {
            "time": time_int if time_int is not None else time_val,
            "key": str(item_key),
            "id": info.get("id") if info else None,
            "name": info.get("name") if info else None,
        }

    player_items: List[Dict[str, Any]] = []
    for p in players:
        player_slot = p.get("player_slot", 0)
        is_radiant = p.get("isRadiant")
        if is_radiant is None:
            is_radiant = player_slot < 128 or p.get("is_radiant") == 1

        hero_id = int(p.get("hero_id", 0) or 0)
        hero_en = hero_map.get(hero_id, f"Hero {hero_id}")
        hero_cn = get_cn_name(hero_en)
        player_name = p.get("name") or p.get("personaname") or p.get("account_id") or "Unknown"

        purchase_log_entries: List[Dict[str, Any]] = []
        for entry in p.get("purchase_log") or []:
            key = entry.get("key")
            if key is None:
                continue
            if not _is_non_consumable(key):
                continue
            purchase_log_entries.append(_build_purchase_entry(key, entry.get("time")))

        purchase_time_entries: List[Dict[str, Any]] = []
        for key, time_val in (p.get("purchase_time") or {}).items():
            if not _is_non_consumable(key):
                continue
            purchase_time_entries.append(_build_purchase_entry(key, time_val))
        purchase_time_entries.sort(
            key=lambda item: item["time"] if isinstance(item.get("time"), int) else 10**9
        )

        player_items.append({
            "player_slot": int(player_slot) if player_slot is not None else None,
            "team": "radiant" if is_radiant else "dire",
            "hero_id": hero_id,
            "hero": hero_cn,
            "hero_en": hero_en,
            "player": str(player_name),
            "purchases": {
                "purchase_log": purchase_log_entries,
                "purchase_time": purchase_time_entries,
            },
        })

    result = {
        "match_id": match_data.get("match_id"),
        "duration": match_data.get("duration"),
        "filter": {"exclude_qual": "consumable"},
        "players": player_items,
    }

    result_str = json.dumps(result, ensure_ascii=False, indent=2)
    logger.info("get_match_items: completed for match_id=%s, result_len=%d", match_id, len(result_str))
    return result_str


@mcp.tool()
async def get_item_id_map(item_ids: List[int]) -> str:
    """
    查询装备 ID 对照表（基于本地 constants_items_map.json）

    Args:
        item_ids: 物品ID列表

    Returns:
        物品ID到名称/Key的映射(JSON)
    """
    logger.info("get_item_id_map called with: item_ids=%s", item_ids)
    if not item_ids:
        return "❌ item_ids 不能为空"

    client = AsyncOpenDotaClient.get_instance()
    by_id = await client.get_cached_item_id_map()
    if not by_id:
        logger.warning("get_item_id_map: no item mapping data available")
        return "❌ 未找到物品映射数据"

    logger.info("get_item_id_map: mapping data loaded, entries=%d", len(by_id))

    items: List[Dict[str, Any]] = []
    missing: List[Any] = []
    for item_id in item_ids:
        try:
            item_id_int = int(item_id)
        except (TypeError, ValueError):
            missing.append(item_id)
            continue
        info = by_id.get(str(item_id_int))
        if info:
            items.append({
                "id": item_id_int,
                "key": info.get("key"),
                "name": info.get("name"),
            })
        else:
            missing.append(item_id_int)

    result = {
        "items": items,
        "missing": missing,
    }

    result_str = json.dumps(result, ensure_ascii=False, indent=2)
    logger.info("get_item_id_map: completed, items=%d, missing=%d", len(items), len(missing))
    return result_str


@mcp.tool()
async def request_match_parse(match_id: int) -> str:
    """
    提交比赛录像解析请求

    Args:
        match_id: Dota 2 比赛ID

    Returns:
        解析请求结果（通常包含 jobId）
    """
    logger.info("request_match_parse called with: match_id=%s", match_id)
    client = AsyncOpenDotaClient.get_instance()
    data = await client.post(f"request/{match_id}")
    if isinstance(data, dict) and "error" in data:
        logger.warning("request_match_parse: API returned error for match_id=%s: %s", match_id, data.get("error"))
        return f"❌ API 错误: {data['error']}"
    logger.info("request_match_parse: completed for match_id=%s, data type=%s", match_id, type(data).__name__)
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
async def request_match_parses(match_ids: List[int]) -> str:
    """
    批量提交比赛录像解析请求

    Args:
        match_ids: 比赛ID列表

    Returns:
        每个比赛ID的解析请求结果列表
    """
    logger.info("request_match_parses called with: match_ids=%s", match_ids)
    client = AsyncOpenDotaClient.get_instance()
    results: List[Dict[str, Any]] = []
    for match_id in match_ids:
        data = await client.post(f"request/{match_id}")
        if isinstance(data, dict) and "error" in data:
            logger.warning("request_match_parses: API returned error for match_id=%s: %s", match_id, data.get("error"))
            results.append({"match_id": match_id, "error": data["error"]})
        else:
            results.append({"match_id": match_id, "response": data})
    result_str = json.dumps(results, ensure_ascii=False, indent=2)
    logger.info("request_match_parses: completed, results_count=%d", len(results))
    return result_str


@mcp.tool()
async def get_parse_request(job_id: str) -> str:
    """
    查询解析请求状态

    Args:
        job_id: 解析请求的 jobId

    Returns:
        解析请求状态信息
    """
    logger.info("get_parse_request called with: job_id=%s", job_id)
    client = AsyncOpenDotaClient.get_instance()
    data = await client.get(f"request/{job_id}")
    if isinstance(data, dict) and "error" in data:
        logger.warning("get_parse_request: API returned error for job_id=%s: %s", job_id, data.get("error"))
        return f"❌ API 错误: {data['error']}"
    logger.info("get_parse_request: completed for job_id=%s, data type=%s", job_id, type(data).__name__)
    return json.dumps(data, ensure_ascii=False, indent=2)
