"""Async hero-related MCP tools for Dota 2 Helper Agent.

Converted from sync tools in dota2_fastmcp.py (lines 2960-3285, 3432-3467,
4148-4241, 4364-4499, 7121-7180). All data fetching is performed via
AsyncOpenDotaClient.
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from post_match_review.mcp_server.server import mcp
from post_match_review.mcp_server.helpers.opendota import AsyncOpenDotaClient
from post_match_review.mcp_server.helpers.hero_names import get_cn_name, get_rank_display
from post_match_review.mcp_server.helpers.rag_index import (
    rank_hero_documents,
    format_hero_rag_output,
    HAS_FAISS,
    HEROES_TXT_DIR,
)


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_heroes() -> str:
    """
    获取所有 Dota 2 英雄的列表

    Returns:
        所有英雄的ID、英文名、中文名、主属性、攻击类型等信息
    """
    logger.info("get_heroes called")
    client = AsyncOpenDotaClient.get_instance()
    heroes = await client.get_heroes()

    if not heroes:
        logger.warning("get_heroes: API returned empty or None")
        return "❌ 获取英雄列表失败"

    logger.info("get_heroes: fetched %d heroes", len(heroes))

    lines = [
        "# Dota 2 英雄列表",
        f"共 {len(heroes)} 个英雄",
        "",
        "| ID | 英文名 | 中文名 | 主属性 | 攻击类型 |",
        "|----|--------|--------|--------|----------|",
    ]

    for hero in heroes:
        en_name = hero.get("localized_name", "")
        cn_name = get_cn_name(en_name)
        lines.append(
            f"| {hero.get('id')} | {en_name} | {cn_name} | "
            f"{hero.get('primary_attr', '')} | {hero.get('attack_type', '')} |"
        )

    result = "\n".join(lines)
    logger.info("get_heroes: completed, result_len=%d", len(result))
    return result


@mcp.tool()
async def rag_hero_intro(query: str, top_k: int = 1, max_chars: int = 0) -> str:
    """
    使用本地 heroes_txt 知识库检索英雄介绍（RAG）

    Args:
        query: 英雄名称或包含英雄名的提问
        top_k: 返回的候选数量，默认1
        max_chars: 每条返回内容的最大字符数，默认4000
    """
    logger.info("rag_hero_intro called with: query=%s, top_k=%s, max_chars=%s", query, top_k, max_chars)
    if not query or not str(query).strip():
        return "❌ query 不能为空"
    if not HAS_FAISS:
        logger.warning("rag_hero_intro: faiss-cpu not installed, cannot perform RAG")
        return "❌ 未安装 faiss-cpu，请先安装依赖后重试。"

    try:
        top_k_int = int(top_k)
    except (TypeError, ValueError):
        logger.warning("rag_hero_intro: invalid top_k=%s, defaulting to 1", top_k)
        top_k_int = 1
    top_k_int = max(1, min(5, top_k_int))

    try:
        max_chars_int = int(max_chars)
    except (TypeError, ValueError):
        logger.warning("rag_hero_intro: invalid max_chars=%s, defaulting to 0", max_chars)
        max_chars_int = 0

    results = rank_hero_documents(str(query), top_k_int)
    if not results:
        if not os.path.isdir(str(HEROES_TXT_DIR)):
            logger.warning("rag_hero_intro: heroes_txt directory not found: %s", HEROES_TXT_DIR)
            return f"❌ 未找到 heroes_txt 目录: {HEROES_TXT_DIR}"
        logger.warning("rag_hero_intro: no matching hero found for query=%s", query)
        return "❌ 未找到匹配英雄，请提供更准确的英雄名称（中英文均可）。"

    logger.info("rag_hero_intro: found %d results for query=%s", len(results), query)
    output = format_hero_rag_output(str(query), results, max_chars_int)
    logger.info("rag_hero_intro: completed, result_len=%d", len(output))
    return output


@mcp.tool()
async def get_hero_matches(hero_id: int, limit: int = 20) -> str:
    """
    获取指定英雄的最近比赛记录

    Args:
        hero_id: 英雄ID
        limit: 返回的比赛数量，默认20

    Returns:
        比赛列表（对阵、阵营、胜负、时长等）
    """
    logger.info("get_hero_matches called with: hero_id=%s, limit=%s", hero_id, limit)
    client = AsyncOpenDotaClient.get_instance()
    data = await client.get(f"heroes/{hero_id}/matches")

    if isinstance(data, dict) and "error" in data:
        logger.warning("get_hero_matches: API returned error: %s", data["error"])
        return f"❌ API 错误: {data['error']}"

    if not isinstance(data, list):
        logger.warning("get_hero_matches: unexpected data type=%s", type(data).__name__)
        return "❌ 获取英雄比赛失败"

    logger.info("get_hero_matches: fetched %d matches for hero_id=%s", len(data), hero_id)

    hero_map = await client.get_cached_hero_map()
    hero_en = hero_map.get(hero_id, f"Hero {hero_id}")
    hero_cn = get_cn_name(hero_en)

    matches = data[:limit]
    lines = [
        f"# 🧭 {hero_cn} 最近比赛",
        "",
        "| Match ID | 对阵 | 阵营 | 结果 | 时长 |",
        "|----------|------|------|------|------|",
    ]

    for m in matches:
        radiant_name = m.get("radiant_name") or "Radiant"
        dire_name = m.get("dire_name") or "Dire"
        side_radiant = bool(m.get("radiant"))
        side = "天辉" if side_radiant else "夜魇"
        radiant_win = m.get("radiant_win")
        if radiant_win is None:
            result = "未知"
        else:
            hero_win = (radiant_win and side_radiant) or (not radiant_win and not side_radiant)
            result = "✅ 胜" if hero_win else "❌ 负"
        duration = int(m.get("duration", 0) or 0)
        minutes, seconds = divmod(duration, 60)

        lines.append(
            f"| {m.get('match_id')} | {radiant_name} vs {dire_name} | "
            f"{side} | {result} | {minutes}:{seconds:02d} |"
        )

    result = "\n".join(lines)
    logger.info("get_hero_matches: completed, result_len=%d", len(result))
    return result


@mcp.tool()
async def get_hero_matchups(hero_id: int, limit: int = 20) -> str:
    """
    获取指定英雄对阵其他英雄的胜负情况

    Args:
        hero_id: 英雄ID
        limit: 返回的对阵数量，默认20

    Returns:
        对阵英雄列表（场次、胜场、胜率）
    """
    logger.info("get_hero_matchups called with: hero_id=%s, limit=%s", hero_id, limit)
    client = AsyncOpenDotaClient.get_instance()
    data = await client.get(f"heroes/{hero_id}/matchups")

    if isinstance(data, dict) and "error" in data:
        logger.warning("get_hero_matchups: API returned error: %s", data["error"])
        return f"❌ API 错误: {data['error']}"

    if not isinstance(data, list):
        logger.warning("get_hero_matchups: unexpected data type=%s", type(data).__name__)
        return "❌ 获取英雄对阵数据失败"

    logger.info("get_hero_matchups: fetched %d matchups for hero_id=%s", len(data), hero_id)

    hero_map = await client.get_cached_hero_map()
    hero_en = hero_map.get(hero_id, f"Hero {hero_id}")
    hero_cn = get_cn_name(hero_en)

    matchups = data[:limit]
    lines = [
        f"# ⚔️ {hero_cn} 对阵英雄",
        "",
        "| 对手英雄 | 场次 | 胜场 | 胜率 |",
        "|----------|------|------|------|",
    ]

    for row in matchups:
        opp_id = int(row.get("hero_id", 0) or 0)
        opp_en = hero_map.get(opp_id, f"Hero {opp_id}")
        opp_cn = get_cn_name(opp_en)
        games = row.get("games_played", 0)
        wins = row.get("wins", 0)
        win_rate = f"{(wins / games * 100):.1f}%" if games > 0 else "N/A"
        lines.append(f"| {opp_cn} | {games} | {wins} | {win_rate} |")

    result = "\n".join(lines)
    logger.info("get_hero_matchups: completed, result_len=%d", len(result))
    return result


@mcp.tool()
async def get_hero_durations(hero_id: int) -> str:
    """
    获取指定英雄在不同时长区间的表现

    Args:
        hero_id: 英雄ID

    Returns:
        不同比赛时长区间的场次与胜率
    """
    logger.info("get_hero_durations called with: hero_id=%s", hero_id)
    client = AsyncOpenDotaClient.get_instance()
    data = await client.get(f"heroes/{hero_id}/durations")

    if isinstance(data, dict) and "error" in data:
        logger.warning("get_hero_durations: API returned error: %s", data["error"])
        return f"❌ API 错误: {data['error']}"

    if not isinstance(data, list):
        logger.warning("get_hero_durations: unexpected data type=%s", type(data).__name__)
        return "❌ 获取英雄时长分布失败"

    logger.info("get_hero_durations: fetched %d duration bins for hero_id=%s", len(data), hero_id)

    hero_map = await client.get_cached_hero_map()
    hero_en = hero_map.get(hero_id, f"Hero {hero_id}")
    hero_cn = get_cn_name(hero_en)

    lines = [
        f"# ⏱️ {hero_cn} 时长分布",
        "",
        "| 时长起点 | 场次 | 胜场 | 胜率 |",
        "|----------|------|------|------|",
    ]

    for row in data:
        duration_bin = row.get("duration_bin")
        try:
            seconds = int(float(duration_bin))
            minutes, secs = divmod(seconds, 60)
            bin_label = f"{minutes}:{secs:02d}"
        except (TypeError, ValueError):
            logger.debug("get_hero_durations: invalid duration_bin=%s", duration_bin)
            bin_label = str(duration_bin)
        games = row.get("games_played", 0)
        wins = row.get("wins", 0)
        win_rate = f"{(wins / games * 100):.1f}%" if games > 0 else "N/A"
        lines.append(f"| {bin_label} | {games} | {wins} | {win_rate} |")

    result = "\n".join(lines)
    logger.info("get_hero_durations: completed, result_len=%d", len(result))
    return result


@mcp.tool()
async def get_hero_players(hero_id: int, limit: int = 20) -> str:
    """
    获取使用指定英雄的玩家列表

    Args:
        hero_id: 英雄ID
        limit: 返回的玩家数量，默认20

    Returns:
        玩家列表（昵称、战队、场次、胜率）
    """
    logger.info("get_hero_players called with: hero_id=%s, limit=%s", hero_id, limit)
    client = AsyncOpenDotaClient.get_instance()
    data = await client.get(f"heroes/{hero_id}/players")

    if isinstance(data, dict) and "error" in data:
        logger.warning("get_hero_players: API returned error: %s", data["error"])
        return f"❌ API 错误: {data['error']}"

    if not isinstance(data, list):
        logger.warning("get_hero_players: unexpected data type=%s", type(data).__name__)
        return "❌ 获取英雄玩家列表失败"

    logger.info("get_hero_players: fetched %d players for hero_id=%s", len(data), hero_id)

    hero_map = await client.get_cached_hero_map()
    hero_en = hero_map.get(hero_id, f"Hero {hero_id}")
    hero_cn = get_cn_name(hero_en)

    players = data[:limit]
    lines = [
        f"# 👥 {hero_cn} 选手列表",
        "",
        "| 玩家 | 战队 | 场次 | 胜场 | 胜率 |",
        "|------|------|------|------|------|",
    ]

    for row in players:
        name = row.get("name") or row.get("personaname") or row.get("account_id") or "Unknown"
        team = row.get("team_name") or row.get("team_tag") or "N/A"
        games = row.get("games", 0)
        wins = row.get("wins", row.get("win", 0))
        win_rate = f"{(wins / games * 100):.1f}%" if games > 0 else "N/A"
        lines.append(f"| {str(name)[:16]} | {str(team)[:12]} | {games} | {wins} | {win_rate} |")

    result = "\n".join(lines)
    logger.info("get_hero_players: completed, result_len=%d", len(result))
    return result


@mcp.tool()
async def get_hero_item_popularity(hero_id: int, limit: int = 8) -> str:
    """
    获取指定英雄的出装流行度（按阶段）

    Args:
        hero_id: 英雄ID
        limit: 每个阶段展示的装备数量，默认8

    Returns:
        开局/前期/中期/后期的热门装备列表
    """
    logger.info("get_hero_item_popularity called with: hero_id=%s, limit=%s", hero_id, limit)
    client = AsyncOpenDotaClient.get_instance()
    data = await client.get(f"heroes/{hero_id}/itemPopularity")

    if isinstance(data, dict) and "error" in data:
        logger.warning("get_hero_item_popularity: API returned error: %s", data["error"])
        return f"❌ API 错误: {data['error']}"

    if not isinstance(data, dict):
        logger.warning("get_hero_item_popularity: unexpected data type=%s", type(data).__name__)
        return "❌ 获取英雄出装流行度失败"

    hero_map = await client.get_cached_hero_map()
    hero_en = hero_map.get(hero_id, f"Hero {hero_id}")
    hero_cn = get_cn_name(hero_en)
    item_map = await client.get_cached_items_map()

    def _resolve_item_name(item_key: Any) -> str:
        try:
            item_id = int(item_key)
        except (TypeError, ValueError):
            logger.debug("get_hero_item_popularity._resolve_item_name: non-integer item_key=%s", item_key)
            item_id = None
        if item_id and item_id in item_map:
            info = item_map[item_id]
            return info.get("name") or info.get("key") or str(item_key)
        return str(item_key)

    def _format_section(title: str, payload: Any) -> List[str]:
        if not isinstance(payload, dict) or not payload:
            return [f"## {title}", "", "暂无数据", ""]
        pairs: List[tuple] = []
        for key, count in payload.items():
            try:
                count_val = int(count)
            except (TypeError, ValueError):
                logger.debug("get_hero_item_popularity._format_section: non-integer count=%s for key=%s", count, key)
                count_val = 0
            pairs.append((_resolve_item_name(key), count_val))
        pairs.sort(key=lambda x: x[1], reverse=True)
        top_items = pairs[:limit]
        section_lines = [
            f"## {title}",
            "",
            "| 装备 | 次数 |",
            "|------|------|",
        ]
        for name, count_val in top_items:
            section_lines.append(f"| {name} | {count_val} |")
        section_lines.append("")
        return section_lines

    sections = [
        ("开局装备", data.get("start_game_items")),
        ("前期装备", data.get("early_game_items")),
        ("中期装备", data.get("mid_game_items")),
        ("后期装备", data.get("late_game_items")),
    ]

    lines: List[str] = [f"# 🧰 {hero_cn} 出装流行度", ""]
    for title, payload in sections:
        lines.extend(_format_section(title, payload))

    result = "\n".join(lines)
    logger.info("get_hero_item_popularity: completed, result_len=%d", len(result))
    return result


@mcp.tool()
async def get_hero_stats() -> str:
    """
    获取所有英雄的统计数据

    Returns:
        英雄的胜率、选取率、禁用率等统计数据（按选取率排序，显示前20）
    """
    logger.info("get_hero_stats called")
    client = AsyncOpenDotaClient.get_instance()
    data = await client.get("heroStats")

    if isinstance(data, dict) and "error" in data:
        logger.warning("get_hero_stats: API returned error: %s", data["error"])
        return f"❌ API 错误: {data['error']}"

    if not isinstance(data, list):
        logger.warning("get_hero_stats: unexpected data type=%s", type(data).__name__)
        return "❌ 获取英雄统计失败"

    logger.info("get_hero_stats: fetched %d hero stats", len(data))

    lines = [
        "# 📊 英雄统计数据 (职业赛事)",
        "",
        "| 英雄 | 选取数 | 胜率 | 禁用数 |",
        "|------|--------|------|--------|",
    ]

    sorted_stats = sorted(data, key=lambda x: x.get("pro_pick", 0), reverse=True)[:20]

    for s in sorted_stats:
        en_name = s.get("localized_name", "")
        cn_name = get_cn_name(en_name)
        picks = s.get("pro_pick", 0)
        wins = s.get("pro_win", 0)
        bans = s.get("pro_ban", 0)
        win_rate = f"{(wins / picks * 100):.1f}%" if picks > 0 else "N/A"

        lines.append(f"| {cn_name} | {picks} | {win_rate} | {bans} |")

    result = "\n".join(lines)
    logger.info("get_hero_stats: completed, result_len=%d", len(result))
    return result


@mcp.tool()
async def get_hero_rankings(hero_id: int) -> str:
    """
    获取指定英雄的排行榜

    Args:
        hero_id: 英雄ID

    Returns:
        该英雄的排行榜，显示顶尖玩家
    """
    logger.info("get_hero_rankings called with: hero_id=%s", hero_id)
    client = AsyncOpenDotaClient.get_instance()
    data = await client.get("rankings", params={"hero_id": hero_id})

    if isinstance(data, dict) and "error" in data:
        logger.warning("get_hero_rankings: API returned error: %s", data["error"])
        return f"❌ API 错误: {data['error']}"

    hero_map = await client.get_cached_hero_map()
    hero_en = hero_map.get(hero_id, f"Hero {hero_id}")
    hero_cn = get_cn_name(hero_en)

    rankings = data.get("rankings", [])[:20]
    logger.info("get_hero_rankings: fetched %d rankings for hero_id=%s", len(data.get("rankings", [])), hero_id)

    lines = [
        f"# 🏅 {hero_cn} 排行榜",
        "",
        "| 排名 | 玩家 | 分数 |",
        "|------|------|------|",
    ]

    for i, r in enumerate(rankings, 1):
        name = r.get("personaname", "Unknown")[:15]
        score = r.get("score", 0)
        lines.append(f"| {i} | {name} | {score:.2f} |")

    result = "\n".join(lines)
    logger.info("get_hero_rankings: completed, result_len=%d", len(result))
    return result


@mcp.tool()
async def get_hero_benchmarks(hero_id: int) -> str:
    """
    获取指定英雄的基准数据（不同百分位的表现标准）

    Args:
        hero_id: 英雄ID

    Returns:
        英雄的基准数据，如GPM、XPM、击杀等在不同百分位的数值
    """
    logger.info("get_hero_benchmarks called with: hero_id=%s", hero_id)
    client = AsyncOpenDotaClient.get_instance()
    data = await client.get("benchmarks", params={"hero_id": hero_id})

    if isinstance(data, dict) and "error" in data:
        logger.warning("get_hero_benchmarks: API returned error: %s", data["error"])
        return f"❌ API 错误: {data['error']}"

    hero_map = await client.get_cached_hero_map()
    hero_en = hero_map.get(hero_id, f"Hero {hero_id}")
    hero_cn = get_cn_name(hero_en)

    result = data.get("result", {})
    logger.info("get_hero_benchmarks: fetched %d benchmark fields for hero_id=%s", len(result), hero_id)

    # 字段中文映射
    field_names: Dict[str, str] = {
        "gold_per_min": "GPM", "xp_per_min": "XPM", "kills_per_min": "每分钟击杀",
        "last_hits_per_min": "每分钟正补", "hero_damage_per_min": "每分钟英雄伤害",
        "hero_healing_per_min": "每分钟治疗", "tower_damage": "建筑伤害",
    }

    lines = [
        f"# 📊 {hero_cn} 基准数据",
        "",
        "| 指标 | 50% | 75% | 90% | 99% |",
        "|------|-----|-----|-----|-----|",
    ]

    for field, cn_name in field_names.items():
        if field in result:
            values = result[field]
            # 提取不同百分位的值
            p50 = p75 = p90 = p99 = "N/A"
            for v in values:
                pct = v.get("percentile", 0)
                val = v.get("value", 0)
                if pct == 0.5:
                    p50 = f"{val:.1f}"
                elif pct == 0.75:
                    p75 = f"{val:.1f}"
                elif pct == 0.9:
                    p90 = f"{val:.1f}"
                elif pct == 0.99:
                    p99 = f"{val:.1f}"

            lines.append(f"| {cn_name} | {p50} | {p75} | {p90} | {p99} |")

    output = "\n".join(lines)
    logger.info("get_hero_benchmarks: completed, result_len=%d", len(output))
    return output


@mcp.tool()
async def get_hero_abilities(hero_id: int, include_talents: bool = True) -> str:
    """
    获取英雄的技能列表（优先本地 constants）

    Args:
        hero_id: 英雄ID
        include_talents: 是否包含天赋，默认False

    Returns:
        英雄技能列表
    """
    logger.info("get_hero_abilities called with: hero_id=%s, include_talents=%s", hero_id, include_talents)
    try:
        hero_id_int = int(hero_id)
    except (TypeError, ValueError):
        logger.warning("get_hero_abilities: invalid hero_id=%s", hero_id)
        return "❌ hero_id 需要是整数"

    client = AsyncOpenDotaClient.get_instance()

    heroes_data = await client.get_cached_constants("heroes")
    if not isinstance(heroes_data, dict):
        logger.warning("get_hero_abilities: heroes constants unexpected type=%s", type(heroes_data).__name__)
        return "❌ heroes 常量格式错误"

    hero_entry = heroes_data.get(str(hero_id_int))
    if not isinstance(hero_entry, dict):
        logger.warning("get_hero_abilities: hero_id=%s not found in constants", hero_id_int)
        return f"❌ 未找到英雄ID: {hero_id_int}"

    hero_name = str(hero_entry.get("name") or "")
    hero_display = str(hero_entry.get("localized_name") or hero_name or f"Hero {hero_id_int}")
    hero_key_short = hero_name.replace("npc_dota_hero_", "") if hero_name else ""

    ability_map = await client.get_cached_constants("abilities")

    abilities_data: Optional[Any] = None
    for resource in ("hero_abilities", "hero_ability", "heroAbilities"):
        data = await client.get_cached_constants(resource)
        if isinstance(data, dict):
            abilities_data = data
            break

    if not isinstance(abilities_data, dict):
        logger.warning("get_hero_abilities: hero_abilities constants not found or wrong type")
        return "❌ 未找到 hero_abilities 常量"

    candidates = [hero_name, hero_key_short, hero_key_short.lower()]
    ability_list: Optional[List[Any]] = None
    for key in candidates:
        if key and key in abilities_data:
            ability_list = abilities_data[key]
            break

    if ability_list is None and hero_key_short:
        for key in abilities_data.keys():
            if key.endswith(hero_key_short):
                ability_list = abilities_data[key]
                break

    if not isinstance(ability_list, list):
        logger.warning("get_hero_abilities: no ability mapping found for hero=%s", hero_display)
        return f"❌ 未找到英雄技能映射: {hero_display}"

    def _is_talent(name: str) -> bool:
        return name.startswith("special_bonus")

    lines: List[str] = [
        f"# 🧠 {hero_display} 技能列表",
        "",
        "| 技能 | 显示名 | 图标 |",
        "|------|--------|------|",
    ]

    for ability in ability_list:
        ability_key = str(ability)
        if not include_talents and _is_talent(ability_key):
            continue
        display_name = ability_key
        icon = ""
        if isinstance(ability_map, dict) and ability_key in ability_map:
            info = ability_map.get(ability_key, {})
            if isinstance(info, dict):
                display_name = info.get("dname") or ability_key
                icon = info.get("img") or ""
        lines.append(f"| {ability_key} | {display_name} | {icon} |")

    facets_data: Optional[Any] = None
    for resource in ("facets", "hero_facets", "hero_facet", "heroFacets"):
        data = await client.get_cached_constants(resource)
        if data is not None:
            facets_data = data
            break

    facets: List[Dict[str, Any]] = []
    hero_key_candidates = [str(hero_id_int), hero_name, hero_key_short, hero_key_short.lower()]
    if isinstance(facets_data, dict):
        for key in hero_key_candidates:
            if key and key in facets_data:
                entries = facets_data.get(key)
                if isinstance(entries, list):
                    facets = entries
                break
        if not facets and hero_key_short:
            for key, entries in facets_data.items():
                if isinstance(key, str) and key.endswith(hero_key_short) and isinstance(entries, list):
                    facets = entries
                    break
    elif isinstance(facets_data, list):
        for entry in facets_data:
            if not isinstance(entry, dict):
                continue
            entry_hero_id = entry.get("hero_id")
            try:
                entry_hero_id = int(entry_hero_id)
            except (TypeError, ValueError):
                logger.debug("get_hero_abilities: non-integer entry_hero_id=%s", entry_hero_id)
                entry_hero_id = None
            if entry_hero_id == hero_id_int:
                facets.append(entry)

    if facets:
        lines.extend(["", "## 命石", "", "| 命石 | 描述 |", "|------|------|"])
        for facet in facets:
            if isinstance(facet, dict):
                name = facet.get("name") or facet.get("title") or facet.get("key") or facet.get("id")
                desc = facet.get("desc") or facet.get("description") or facet.get("summary") or ""
            else:
                name = str(facet)
                desc = ""
            lines.append(f"| {name or '未知'} | {desc} |")
    else:
        lines.extend(["", "## 命石", "", "未找到命石数据"])

    result = "\n".join(lines)
    logger.info("get_hero_abilities: completed, result_len=%d", len(result))
    return result


@mcp.tool()
async def get_live_matches(limit: int = 10) -> str:
    """
    获取正在进行的实时比赛

    Args:
        limit: 返回的比赛数量，默认10

    Returns:
        正在进行的高分比赛列表，按MMR排序
    """
    logger.info("get_live_matches called with: limit=%s", limit)
    client = AsyncOpenDotaClient.get_instance()
    data = await client.get("live")

    if isinstance(data, dict) and "error" in data:
        logger.warning("get_live_matches: API returned error: %s", data["error"])
        return f"❌ API 错误: {data['error']}"

    if not isinstance(data, list):
        logger.warning("get_live_matches: unexpected data type=%s", type(data).__name__)
        return "❌ 获取实时比赛失败"

    if not data:
        logger.info("get_live_matches: no live matches available")
        return "当前没有正在进行的比赛"

    logger.info("get_live_matches: fetched %d live matches", len(data))

    # 按 MMR 排序
    sorted_matches = sorted(data, key=lambda x: x.get("average_mmr", 0), reverse=True)[:limit]

    hero_map = await client.get_cached_hero_map()

    lines: List[str] = [
        f"# 🔴 正在进行的比赛 ({len(data)} 场)",
        "",
    ]

    for i, m in enumerate(sorted_matches, 1):
        match_id = m.get("match_id", "N/A")
        avg_mmr = m.get("average_mmr", 0)
        game_time = m.get("game_time", 0)
        minutes = game_time // 60
        seconds = game_time % 60

        radiant_score = m.get("radiant_score", 0)
        dire_score = m.get("dire_score", 0)
        spectators = m.get("spectators", 0)

        lines.append(f"## [{i}] Match {match_id}")
        lines.append(f"- MMR: {avg_mmr} | 时间: {minutes}:{seconds:02d} | 观众: {spectators}")
        lines.append(f"- 比分: 天辉 {radiant_score} - {dire_score} 夜魇")

        # 显示英雄
        players = m.get("players", [])
        radiant = [p for p in players if p.get("team") == 0]
        dire = [p for p in players if p.get("team") == 1]

        radiant_heroes = [get_cn_name(hero_map.get(p.get("hero_id"), "?")) for p in radiant]
        dire_heroes = [get_cn_name(hero_map.get(p.get("hero_id"), "?")) for p in dire]

        lines.append(f"- 天辉: {', '.join(radiant_heroes)}")
        lines.append(f"- 夜魇: {', '.join(dire_heroes)}")
        lines.append("")

    result = "\n".join(lines)
    logger.info("get_live_matches: completed, result_len=%d", len(result))
    return result
