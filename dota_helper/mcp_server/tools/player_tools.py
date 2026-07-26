"""Player tools — async MCP tools for Dota 2 player data.

Migrated from dota2_fastmcp.py (lines 3286-3620, 4682).
All sync _make_request calls replaced with AsyncOpenDotaClient.get().
_build_hero_map() replaced with client.get_cached_hero_map().
_format_rank_tier() replaced with get_rank_display().
_get_cn_name() replaced with get_cn_name().
"""

import logging
from typing import Dict

from dota_helper.mcp_server.server import mcp
from dota_helper.mcp_server.helpers.opendota import AsyncOpenDotaClient
from dota_helper.mcp_server.helpers.hero_names import get_cn_name, get_rank_display
from dota_helper.mcp_server.helpers.map_config import format_time_mmss

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_player_info(account_id: int) -> str:
    """
    获取指定玩家的基本信息

    Args:
        account_id: Steam 32位账号ID

    Returns:
        玩家的昵称、Steam ID、天梯段位等信息
    """
    logger.info("get_player_info called with: account_id=%s", account_id)
    try:
        client = AsyncOpenDotaClient.get_instance()
        data = await client.get(f"players/{account_id}")

        if isinstance(data, dict) and "error" in data:
            logger.warning("get_player_info: API returned error for account_id=%s: %s", account_id, data["error"])
            return f"❌ API 错误: {data['error']}"

        logger.info("get_player_info: fetched data for account_id=%s", account_id)

        profile = data.get("profile", {})

        lines = [
            "# 👤 玩家信息",
            "",
            f"- 昵称: {profile.get('personaname', 'Unknown')}",
            f"- Steam ID: {profile.get('steamid', 'N/A')}",
            f"- 账号 ID: {profile.get('account_id', 'N/A')}",
        ]

        if data.get("rank_tier") is not None:
            rank_tier = data.get("rank_tier")
            rank_text = get_rank_display(rank_tier)
            if rank_text:
                lines.append(f"- 天梯段位: {rank_text}（{rank_tier}）")
            else:
                lines.append(f"- 天梯段位: {rank_tier}")

        if data.get("leaderboard_rank"):
            lines.append(f"- 排行榜排名: {data.get('leaderboard_rank')}")

        if profile.get("profileurl"):
            lines.append(f"- Steam 主页: {profile.get('profileurl')}")

        result = "\n".join(lines)
        logger.info("get_player_info: completed for account_id=%s, result_len=%d", account_id, len(result))
        return result
    except Exception as e:
        logger.error("get_player_info: failed for account_id=%s: %s", account_id, e, exc_info=True)
        raise


@mcp.tool()
async def get_player_matches(account_id: int, limit: int = 50) -> str:
    """
    获取指定玩家最近的比赛记录

    Args:
        account_id: Steam 32位账号ID
        limit: 返回的比赛数量，默认10

    Returns:
        玩家最近的比赛列表，包括使用的英雄、KDA、胜负等
    """
    logger.info("get_player_matches called with: account_id=%s", account_id)
    try:
        client = AsyncOpenDotaClient.get_instance()
        data = await client.get(f"players/{account_id}/recentMatches")

        if isinstance(data, dict) and "error" in data:
            logger.warning("get_player_matches: API returned error for account_id=%s: %s", account_id, data["error"])
            return f"❌ API 错误: {data['error']}"

        if not isinstance(data, list):
            logger.warning("get_player_matches: unexpected data type=%s for account_id=%s", type(data).__name__, account_id)
            return "❌ 获取比赛记录失败"

        logger.info("get_player_matches: fetched data for account_id=%s", account_id)

        matches = data[:limit]
        hero_map: Dict[int, str] = await client.get_cached_hero_map()

        lines = [
            "# 📋 最近比赛记录",
            "",
            "| Match ID | 英雄 | K/D/A | 结果 | 时长 |",
            "|----------|------|-------|------|------|",
        ]

        for m in matches:
            hero_en = hero_map.get(m.get("hero_id"), f"Hero {m.get('hero_id')}")
            hero_cn = get_cn_name(hero_en)
            kda = f"{m.get('kills', 0)}/{m.get('deaths', 0)}/{m.get('assists', 0)}"

            radiant_win = m.get("radiant_win")
            is_radiant = m.get("player_slot", 128) < 128
            won = (radiant_win and is_radiant) or (not radiant_win and not is_radiant)
            result = "✅ 胜" if won else "❌ 负"

            duration = m.get("duration", 0)
            minutes, seconds = divmod(duration, 60)

            lines.append(f"| {m.get('match_id')} | {hero_cn} | {kda} | {result} | {minutes}:{seconds:02d} |")

        result = "\n".join(lines)
        logger.info("get_player_matches: completed for account_id=%s, result_len=%d", account_id, len(result))
        return result
    except Exception as e:
        logger.error("get_player_matches: failed for account_id=%s: %s", account_id, e, exc_info=True)
        raise


@mcp.tool()
async def get_player_win_loss(account_id: int) -> str:
    """
    获取指定玩家的胜负统计

    Args:
        account_id: Steam 32位账号ID

    Returns:
        玩家的胜场、负场、总场次和胜率
    """
    logger.info("get_player_win_loss called with: account_id=%s", account_id)
    try:
        client = AsyncOpenDotaClient.get_instance()
        data = await client.get(f"players/{account_id}/wl")

        if isinstance(data, dict) and "error" in data:
            logger.warning("get_player_win_loss: API returned error for account_id=%s: %s", account_id, data["error"])
            return f"❌ API 错误: {data['error']}"

        logger.info("get_player_win_loss: fetched data for account_id=%s", account_id)

        wins = data.get("win", 0)
        losses = data.get("lose", 0)
        total = wins + losses
        win_rate = f"{(wins / total * 100):.1f}%" if total > 0 else "N/A"

        result = f"""# 📈 胜负统计

- ✅ 胜场: {wins}
- ❌ 负场: {losses}
- 📊 总场次: {total}
- 🎯 胜率: {win_rate}
"""
        logger.info("get_player_win_loss: completed for account_id=%s, result_len=%d", account_id, len(result))
        return result
    except Exception as e:
        logger.error("get_player_win_loss: failed for account_id=%s: %s", account_id, e, exc_info=True)
        raise


@mcp.tool()
async def get_player_heroes(account_id: int, limit: int = 10) -> str:
    """
    获取指定玩家最常用的英雄列表

    Args:
        account_id: Steam 32位账号ID
        limit: 返回的英雄数量，默认10

    Returns:
        玩家最常用的英雄，包括场次、胜场和胜率
    """
    logger.info("get_player_heroes called with: account_id=%s", account_id)
    try:
        client = AsyncOpenDotaClient.get_instance()
        data = await client.get(f"players/{account_id}/heroes")

        if isinstance(data, dict) and "error" in data:
            logger.warning("get_player_heroes: API returned error for account_id=%s: %s", account_id, data["error"])
            return f"❌ API 错误: {data['error']}"

        if not isinstance(data, list):
            logger.warning("get_player_heroes: unexpected data type=%s for account_id=%s", type(data).__name__, account_id)
            return "❌ 获取玩家英雄数据失败"

        logger.info("get_player_heroes: fetched data for account_id=%s", account_id)

        heroes = data[:limit]
        hero_map: Dict[int, str] = await client.get_cached_hero_map()

        lines = [
            "# 🎮 常用英雄",
            "",
            "| 英雄 | 场次 | 胜场 | 胜率 |",
            "|------|------|------|------|",
        ]

        for h in heroes:
            hero_en = hero_map.get(int(h.get("hero_id", 0)), f"Hero {h.get('hero_id')}")
            hero_cn = get_cn_name(hero_en)
            games = h.get("games", 0)
            wins = h.get("win", 0)
            win_rate = f"{(wins / games * 100):.1f}%" if games > 0 else "N/A"

            lines.append(f"| {hero_cn} | {games} | {wins} | {win_rate} |")

        result = "\n".join(lines)
        logger.info("get_player_heroes: completed for account_id=%s, result_len=%d", account_id, len(result))
        return result
    except Exception as e:
        logger.error("get_player_heroes: failed for account_id=%s: %s", account_id, e, exc_info=True)
        raise


@mcp.tool()
async def get_player_peers(account_id: int, limit: int = 10) -> str:
    """
    获取指定玩家最常一起游戏的队友

    Args:
        account_id: Steam 32位账号ID
        limit: 返回的队友数量，默认10

    Returns:
        玩家最常合作的队友列表，包括一起游戏的场次、胜场和胜率
    """
    logger.info("get_player_peers called with: account_id=%s", account_id)
    try:
        client = AsyncOpenDotaClient.get_instance()
        data = await client.get(f"players/{account_id}/peers")

        if isinstance(data, dict) and "error" in data:
            logger.warning("get_player_peers: API returned error for account_id=%s: %s", account_id, data["error"])
            return f"❌ API 错误: {data['error']}"

        if not isinstance(data, list):
            logger.warning("get_player_peers: unexpected data type=%s for account_id=%s", type(data).__name__, account_id)
            return "❌ 获取队友数据失败"

        logger.info("get_player_peers: fetched data for account_id=%s", account_id)

        peers = data[:limit]

        lines = [
            "# 👥 常合作队友",
            "",
            "| 昵称 | 一起场次 | 一起胜场 | 胜率 |",
            "|------|----------|----------|------|",
        ]

        for p in peers:
            name = p.get("personaname", "Unknown")[:15]
            games = p.get("with_games", 0)
            wins = p.get("with_win", 0)
            win_rate = f"{(wins / games * 100):.1f}%" if games > 0 else "N/A"

            lines.append(f"| {name} | {games} | {wins} | {win_rate} |")

        result = "\n".join(lines)
        logger.info("get_player_peers: completed for account_id=%s, result_len=%d", account_id, len(result))
        return result
    except Exception as e:
        logger.error("get_player_peers: failed for account_id=%s: %s", account_id, e, exc_info=True)
        raise


@mcp.tool()
async def get_player_totals(account_id: int) -> str:
    """
    获取指定玩家的统计总计数据

    Args:
        account_id: Steam 32位账号ID

    Returns:
        玩家的各项统计总计，如总击杀、总死亡、总助攻、总GPM等
    """
    logger.info("get_player_totals called with: account_id=%s", account_id)
    try:
        client = AsyncOpenDotaClient.get_instance()
        data = await client.get(f"players/{account_id}/totals")

        if isinstance(data, dict) and "error" in data:
            logger.warning("get_player_totals: API returned error for account_id=%s: %s", account_id, data["error"])
            return f"❌ API 错误: {data['error']}"

        if not isinstance(data, list):
            logger.warning("get_player_totals: unexpected data type=%s for account_id=%s", type(data).__name__, account_id)
            return "❌ 获取统计数据失败"

        logger.info("get_player_totals: fetched data for account_id=%s", account_id)

        # 字段中文映射
        field_names = {
            "kills": "击杀", "deaths": "死亡", "assists": "助攻",
            "gold_per_min": "GPM", "xp_per_min": "XPM", "last_hits": "正补",
            "denies": "反补", "hero_damage": "英雄伤害", "tower_damage": "建筑伤害",
            "hero_healing": "治疗量", "stuns": "眩晕时长(秒)",
        }

        lines = [
            "# 📊 玩家统计总计",
            "",
            "| 统计项 | 总计 | 场次 | 场均 |",
            "|--------|------|------|------|",
        ]

        for item in data:
            field = item.get("field", "")
            if field in field_names:
                cn_name = field_names[field]
                total = item.get("sum", 0)
                n = item.get("n", 0)
                avg = f"{total / n:.1f}" if n > 0 else "N/A"
                lines.append(f"| {cn_name} | {total:.0f} | {n} | {avg} |")

        result = "\n".join(lines)
        logger.info("get_player_totals: completed for account_id=%s, result_len=%d", account_id, len(result))
        return result
    except Exception as e:
        logger.error("get_player_totals: failed for account_id=%s: %s", account_id, e, exc_info=True)
        raise


@mcp.tool()
async def search_players(query: str) -> str:
    """
    搜索玩家

    Args:
        query: 搜索关键词（玩家昵称）

    Returns:
        匹配的玩家列表，包括账号ID、昵称等
    """
    logger.info("search_players called with: query=%s", query)
    try:
        client = AsyncOpenDotaClient.get_instance()
        data = await client.get("search", params={"q": query})

        if isinstance(data, dict) and "error" in data:
            logger.warning("search_players: API returned error for query=%s: %s", query, data["error"])
            return f"❌ API 错误: {data['error']}"

        if not isinstance(data, list):
            logger.warning("search_players: unexpected data type=%s for query=%s", type(data).__name__, query)
            return "❌ 搜索失败"

        logger.info("search_players: fetched data for query=%s", query)

        if not data:
            return f"❌ 未找到匹配 '{query}' 的玩家"

        lines = [
            f"# 🔍 搜索结果: {query}",
            "",
            "| 账号ID | 昵称 | 相似度 |",
            "|--------|------|--------|",
        ]

        for p in data[:20]:
            account_id = p.get("account_id", "N/A")
            name = p.get("personaname", "Unknown")[:20]
            similarity = p.get("similarity", 0)

            lines.append(f"| {account_id} | {name} | {similarity:.2f} |")

        result = "\n".join(lines)
        logger.info("search_players: completed for query=%s, result_len=%d", query, len(result))
        return result
    except Exception as e:
        logger.error("search_players: failed for query=%s: %s", query, e, exc_info=True)
        raise
