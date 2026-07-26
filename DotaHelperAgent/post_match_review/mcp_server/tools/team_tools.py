"""Team tools — async MCP tools for Dota 2 team/pro data.

Migrated from dota2_fastmcp.py (lines 3470-4145).
All sync _make_request calls replaced with AsyncOpenDotaClient.get().
_build_hero_map() replaced with client.get_cached_hero_map().
_get_cn_name() replaced with get_cn_name().
"""

import asyncio
import logging
from typing import Dict

from post_match_review.mcp_server.server import mcp
from post_match_review.mcp_server.helpers.opendota import AsyncOpenDotaClient
from post_match_review.mcp_server.helpers.hero_names import get_cn_name, get_rank_display
from post_match_review.mcp_server.helpers.map_config import format_time_mmss

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_pro_matches(limit: int = 20) -> str:
    """
    获取最近的职业比赛列表

    Args:
        limit: 返回的比赛数量，默认20

    Returns:
        最近的职业比赛，包括联赛、队伍、获胜方等
    """
    logger.info("get_pro_matches called with: limit=%s", limit)
    try:
        client = AsyncOpenDotaClient.get_instance()
        data = await client.get("proMatches")

        if isinstance(data, dict) and "error" in data:
            logger.warning("get_pro_matches: API returned error: %s", data['error'])
            return f"❌ API 错误: {data['error']}"

        if not isinstance(data, list):
            logger.warning("get_pro_matches: unexpected data type=%s", type(data).__name__)
            return "❌ 获取职业比赛失败"

        logger.info("get_pro_matches: fetched %d items", len(data))
        matches = data[:limit]

        lines = [
            "# 🏆 最近职业比赛",
            "",
            "| Match ID | 联赛 | 天辉 | 夜魇 | 获胜方 |",
            "|----------|------|------|------|--------|",
        ]

        for m in matches:
            winner = "🟢 天辉" if m.get("radiant_win") else "🔴 夜魇"
            lines.append(
                f"| {m.get('match_id')} | {m.get('league_name', 'N/A')[:20]} | "
                f"{m.get('radiant_name', 'Radiant')[:12]} | {m.get('dire_name', 'Dire')[:12]} | {winner} |"
            )

        result = "\n".join(lines)
        logger.info("get_pro_matches: completed, result_len=%d", len(result))
        return result
    except Exception as e:
        logger.error("get_pro_matches: failed: %s", e, exc_info=True)
        raise


@mcp.tool()
async def get_pro_players(limit: int = 20) -> str:
    """
    获取职业选手列表

    Args:
        limit: 返回的选手数量，默认20

    Returns:
        职业选手列表，包括ID、昵称、所属战队等
    """
    logger.info("get_pro_players called with: limit=%s", limit)
    try:
        client = AsyncOpenDotaClient.get_instance()
        data = await client.get("proPlayers")

        if isinstance(data, dict) and "error" in data:
            logger.warning("get_pro_players: API returned error: %s", data['error'])
            return f"❌ API 错误: {data['error']}"

        if not isinstance(data, list):
            logger.warning("get_pro_players: unexpected data type=%s", type(data).__name__)
            return "❌ 获取职业选手列表失败"

        logger.info("get_pro_players: fetched %d items", len(data))
        players = data[:limit]

        lines = [
            "# 🎮 职业选手列表",
            "",
            "| 账号ID | 昵称 | 战队 | 国家 |",
            "|--------|------|------|------|",
        ]

        for p in players:
            account_id = p.get("account_id", "N/A")
            name = p.get("name", p.get("personaname", "Unknown"))[:15]
            team = p.get("team_name", "N/A")[:12]
            country = p.get("country_code", "N/A")

            lines.append(f"| {account_id} | {name} | {team} | {country} |")

        result = "\n".join(lines)
        logger.info("get_pro_players: completed, result_len=%d", len(result))
        return result
    except Exception as e:
        logger.error("get_pro_players: failed: %s", e, exc_info=True)
        raise


@mcp.tool()
async def get_teams(limit: int = 20) -> str:
    """
    获取战队列表（按评分排序）

    Args:
        limit: 返回的战队数量，默认20

    Returns:
        战队列表，包括战队名、标签、评分、胜负场次
    """
    logger.info("get_teams called with: limit=%s", limit)
    try:
        client = AsyncOpenDotaClient.get_instance()
        data = await client.get("teams")

        if isinstance(data, dict) and "error" in data:
            logger.warning("get_teams: API returned error: %s", data['error'])
            return f"❌ API 错误: {data['error']}"

        if not isinstance(data, list):
            logger.warning("get_teams: unexpected data type=%s", type(data).__name__)
            return "❌ 获取战队列表失败"

        logger.info("get_teams: fetched %d items", len(data))
        teams = data[:limit]

        lines = [
            "# 🏆 战队列表 (按评分排序)",
            "",
            "| 战队ID | 名称 | 标签 | 评分 | 胜/负 |",
            "|--------|------|------|------|-------|",
        ]

        for t in teams:
            team_id = t.get("team_id", "N/A")
            name = t.get("name", "Unknown")[:15]
            tag = t.get("tag", "N/A")[:8]
            rating = f"{t.get('rating', 0):.0f}"
            wins = t.get("wins", 0)
            losses = t.get("losses", 0)

            lines.append(f"| {team_id} | {name} | {tag} | {rating} | {wins}/{losses} |")

        result = "\n".join(lines)
        logger.info("get_teams: completed, result_len=%d", len(result))
        return result
    except Exception as e:
        logger.error("get_teams: failed: %s", e, exc_info=True)
        raise


@mcp.tool()
async def get_team_info(team_id: int) -> str:
    """
    获取指定战队的详细信息

    Args:
        team_id: 战队ID

    Returns:
        战队详细信息，包括名称、评分、胜负场次等
    """
    logger.info("get_team_info called with: team_id=%s", team_id)
    try:
        client = AsyncOpenDotaClient.get_instance()
        data = await client.get(f"teams/{team_id}")

        if isinstance(data, dict) and "error" in data:
            logger.warning("get_team_info: API returned error: %s", data['error'])
            return f"❌ API 错误: {data['error']}"

        if not data:
            logger.warning("get_team_info: unexpected data type=%s", type(data).__name__)
            return "❌ 获取战队信息失败"

        wins = data.get("wins", 0)
        losses = data.get("losses", 0)
        total = wins + losses
        win_rate = f"{(wins / total * 100):.1f}%" if total > 0 else "N/A"

        result = f"""# 🏆 战队信息

- 名称: {data.get('name', 'Unknown')}
- 标签: {data.get('tag', 'N/A')}
- 战队ID: {data.get('team_id', 'N/A')}
- 评分: {data.get('rating', 'N/A')}
- 胜场: {wins}
- 负场: {losses}
- 胜率: {win_rate}
"""
        logger.info("get_team_info: completed, result_len=%d", len(result))
        return result
    except Exception as e:
        logger.error("get_team_info: failed: %s", e, exc_info=True)
        raise


@mcp.tool()
async def get_team_matches(team_id: int, limit: int = 10) -> str:
    """
    获取指定战队的最近比赛列表

    Args:
        team_id: 战队ID
        limit: 返回的比赛数量，默认10

    Returns:
        战队最近比赛列表，包括对手、结果、联赛等
    """
    logger.info("get_team_matches called with: team_id=%s, limit=%s", team_id, limit)
    try:
        client = AsyncOpenDotaClient.get_instance()
        data = await client.get(f"teams/{team_id}/matches")

        if isinstance(data, dict) and "error" in data:
            logger.warning("get_team_matches: API returned error: %s", data['error'])
            return f"❌ API 错误: {data['error']}"

        if not isinstance(data, list):
            logger.warning("get_team_matches: unexpected data type=%s", type(data).__name__)
            return "❌ 获取战队比赛失败"

        logger.info("get_team_matches: fetched %d items", len(data))

        matches = data[:limit]

        hero_map: Dict[int, str] = await client.get_cached_hero_map()

        async def _team_heroes_from_match(match_id: int) -> str:
            """Fetch the team's hero lineup for a single match (with retry)."""
            for attempt in range(2):
                match_data = await client.get(f"matches/{match_id}")
                if isinstance(match_data, dict) and "error" in match_data:
                    if attempt == 0:
                        logger.warning("_team_heroes_from_match: retry attempt %d for match_id=%s", attempt + 1, match_id)
                        await asyncio.sleep(0.4)
                        continue
                    logger.warning("_team_heroes_from_match: API error after retries for match_id=%s", match_id)
                    return "未知"
                if not isinstance(match_data, dict):
                    if attempt == 0:
                        logger.warning("_team_heroes_from_match: retry attempt %d for match_id=%s", attempt + 1, match_id)
                        await asyncio.sleep(0.4)
                        continue
                    logger.warning("_team_heroes_from_match: unexpected data type=%s for match_id=%s after retries", type(match_data).__name__, match_id)
                    return "未知"
                players = match_data.get("players", [])
                if not players:
                    if attempt == 0:
                        logger.warning("_team_heroes_from_match: retry attempt %d for match_id=%s", attempt + 1, match_id)
                        await asyncio.sleep(0.4)
                        continue
                    logger.warning("_team_heroes_from_match: empty players for match_id=%s after retries", match_id)
                    return "未知"

                side = None
                if match_data.get("radiant_team_id") == team_id:
                    side = "radiant"
                elif match_data.get("dire_team_id") == team_id:
                    side = "dire"
                if not side:
                    return "未知"

                hero_names = []
                for p in players:
                    slot = p.get("player_slot", 128)
                    is_radiant = slot < 128
                    if (side == "radiant" and not is_radiant) or (side == "dire" and is_radiant):
                        continue
                    hero_id = p.get("hero_id")
                    if hero_id is None:
                        continue
                    hero_en = hero_map.get(int(hero_id), f"Hero {hero_id}")
                    hero_names.append(get_cn_name(hero_en))

                if hero_names:
                    logger.info("_team_heroes_from_match: found %d heroes for match_id=%s", len(hero_names), match_id)
                    return ", ".join(hero_names)
            logger.warning("_team_heroes_from_match: fallback to unknown for match_id=%s", match_id)
            return "未知"

        lines = [
            "# 🎮 战队最近比赛",
            "",
            "| Match ID | 对手 | 结果 | 时长 | 联赛 | 本队英雄 |",
            "|----------|------|------|------|------|----------|",
        ]

        for m in matches:
            match_id = m.get("match_id", "N/A")
            opponent = m.get("opposing_team_name", "Unknown")

            radiant_win = m.get("radiant_win")
            radiant = m.get("radiant", False)
            if radiant_win is not None:
                team_win = (radiant and radiant_win) or (not radiant and not radiant_win)
                result = "✅ 胜" if team_win else "❌ 负"
            else:
                result = "⏳"

            duration = m.get("duration", 0)
            minutes = duration // 60
            league = m.get("league_name", "N/A")

            team_heroes = await _team_heroes_from_match(int(match_id)) if str(match_id).isdigit() else "未知"
            lines.append(f"| {match_id} | {opponent} | {result} | {minutes}分 | {league} | {team_heroes} |")

        result = "\n".join(lines)
        logger.info("get_team_matches: completed, result_len=%d", len(result))
        return result
    except Exception as e:
        logger.error("get_team_matches: failed: %s", e, exc_info=True)
        raise


@mcp.tool()
async def get_team_players(team_id: int) -> str:
    """
    获取战队选手列表

    Args:
        team_id: 战队ID

    Returns:
        战队选手列表（account_id、name、games_played、wins、is_current_team_member）
    """
    logger.info("get_team_players called with: team_id=%s", team_id)
    try:
        client = AsyncOpenDotaClient.get_instance()
        data = await client.get(f"teams/{team_id}/players")

        if isinstance(data, dict) and "error" in data:
            logger.warning("get_team_players: API returned error: %s", data['error'])
            return f"❌ API 错误: {data['error']}"

        if not isinstance(data, list):
            logger.warning("get_team_players: unexpected data type=%s", type(data).__name__)
            return "❌ 获取战队选手失败"

        players = data

        logger.info("get_team_players: fetched %d items", len(data))

        lines = [
            "# 👥 战队选手列表",
            "",
            "| account_id | name | games_played | wins | is_current_team_member |",
            "|------------|------|--------------|------|------------------------|",
        ]

        for p in players:
            account_id = p.get("account_id", "N/A")
            name = p.get("name", "—")
            games_played = p.get("games_played", 0)
            wins = p.get("wins", 0)
            is_current = "true" if p.get("is_current_team_member") else "false"

            lines.append(f"| {account_id} | {name} | {games_played} | {wins} | {is_current} |")

        result = "\n".join(lines)
        logger.info("get_team_players: completed, result_len=%d", len(result))
        return result
    except Exception as e:
        logger.error("get_team_players: failed: %s", e, exc_info=True)
        raise


@mcp.tool()
async def get_team_heroes(team_id: int, limit: int = 20) -> str:
    """
    获取战队常用英雄

    Args:
        team_id: 战队ID
        limit: 返回的英雄数量，默认20

    Returns:
        战队常用英雄列表
    """
    logger.info("get_team_heroes called with: team_id=%s, limit=%s", team_id, limit)
    try:
        client = AsyncOpenDotaClient.get_instance()
        data = await client.get(f"teams/{team_id}/heroes")

        if isinstance(data, dict) and "error" in data:
            logger.warning("get_team_heroes: API returned error: %s", data['error'])
            return f"❌ API 错误: {data['error']}"

        if not isinstance(data, list):
            logger.warning("get_team_heroes: unexpected data type=%s", type(data).__name__)
            return "❌ 获取战队英雄数据失败"

        logger.info("get_team_heroes: fetched %d items", len(data))

        heroes = data[:limit]
        hero_map: Dict[int, str] = await client.get_cached_hero_map()

        lines = [
            "# 🎯 战队常用英雄",
            "",
            "| 英雄ID | 英雄名 | 场次 | 胜场 | 胜率 |",
            "|--------|--------|------|------|------|",
        ]

        for h in heroes:
            hero_id = int(h.get("hero_id", 0))
            hero_name = hero_map.get(hero_id, f"Hero {hero_id}")
            games = h.get("games_played", 0)
            wins = h.get("wins", 0)
            win_rate = f"{(wins / games * 100):.1f}%" if games > 0 else "N/A"
            lines.append(f"| {hero_id} | {hero_name} | {games} | {wins} | {win_rate} |")

        result = "\n".join(lines)
        logger.info("get_team_heroes: completed, result_len=%d", len(result))
        return result
    except Exception as e:
        logger.error("get_team_heroes: failed: %s", e, exc_info=True)
        raise


@mcp.tool()
async def search_team(team_name: str) -> str:
    """
    通过战队名搜索战队并获取其最近比赛

    Args:
        team_name: 战队名称或标签（如 "Team Spirit", "TSpirit", "OG", "LGD"）

    Returns:
        匹配的战队信息及其最近比赛
    """
    logger.info("search_team called with: team_name=%s", team_name)
    try:
        client = AsyncOpenDotaClient.get_instance()

        # 获取战队列表
        teams_data = await client.get("teams")

        if isinstance(teams_data, dict) and "error" in teams_data:
            logger.warning("search_team: API returned error: %s", teams_data['error'])
            return f"❌ API 错误: {teams_data['error']}"

        if not isinstance(teams_data, list):
            logger.warning("search_team: unexpected data type=%s", type(teams_data).__name__)
            return "❌ 获取战队列表失败"

        team_name_lower = team_name.lower()

        # 精确匹配
        found_team = None
        for team in teams_data:
            if team.get("name", "").lower() == team_name_lower:
                found_team = team
                break
            if team.get("tag", "").lower() == team_name_lower:
                found_team = team
                break

        if found_team:
            logger.info("search_team: exact match found, team_id=%s, name=%s", found_team.get("team_id"), found_team.get("name"))

        # 模糊匹配
        if not found_team:
            matches = []
            for team in teams_data:
                name = team.get("name", "").lower()
                tag = team.get("tag", "").lower()
                if team_name_lower in name or team_name_lower in tag:
                    matches.append(team)

            if len(matches) == 1:
                found_team = matches[0]
                logger.info("search_team: fuzzy match found 1 result, team_id=%s, name=%s", found_team.get("team_id"), found_team.get("name"))
            elif len(matches) > 1:
                logger.info("search_team: fuzzy match found %d results for team_name=%s", len(matches), team_name)
                lines = [f"# 🔍 找到 {len(matches)} 个匹配的战队", ""]
                for t in matches[:10]:
                    lines.append(f"- {t.get('name')} ({t.get('tag')}) - ID: {t.get('team_id')}")
                lines.append("")
                lines.append("请使用更精确的名称或使用 `get_team_matches(team_id)` 指定战队ID")
                return "\n".join(lines)

        if not found_team:
            logger.info("search_team: no match found for team_name=%s", team_name)
            return f"❌ 未找到战队: {team_name}\n提示: 尝试使用战队标签或完整名称"

        # 获取战队比赛
        team_id = found_team.get("team_id")
        wins = found_team.get("wins", 0)
        losses = found_team.get("losses", 0)

        lines = [
            f"# 🏆 {found_team.get('name')} ({found_team.get('tag')})",
            "",
            f"- 战队ID: {team_id}",
            f"- 评分: {found_team.get('rating', 'N/A'):.0f}",
            f"- 战绩: {wins} 胜 / {losses} 负",
            "",
        ]

        # 获取最近比赛
        matches_data = await client.get(f"teams/{team_id}/matches")

        if isinstance(matches_data, list) and matches_data:
            lines.append("## 最近比赛")
            lines.append("")
            lines.append("| Match ID | 对手 | 结果 | 时长 |")
            lines.append("|----------|------|------|------|")

            for m in matches_data[:10]:
                match_id = m.get("match_id", "N/A")
                opponent = m.get("opposing_team_name", "Unknown")

                radiant_win = m.get("radiant_win")
                radiant = m.get("radiant", False)
                if radiant_win is not None:
                    team_win = (radiant and radiant_win) or (not radiant and not radiant_win)
                    result = "✅ 胜" if team_win else "❌ 负"
                else:
                    result = "⏳"

                duration = m.get("duration", 0)
                minutes = duration // 60

                lines.append(f"| {match_id} | {opponent} | {result} | {minutes}分 |")

        result = "\n".join(lines)
        logger.info("search_team: completed, result_len=%d", len(result))
        return result
    except Exception as e:
        logger.error("search_team: failed: %s", e, exc_info=True)
        raise


@mcp.tool()
async def get_leagues(limit: int = 20) -> str:
    """
    获取联赛列表

    Args:
        limit: 返回的联赛数量，默认20

    Returns:
        联赛列表，包括联赛ID、名称、等级等
    """
    logger.info("get_leagues called with: limit=%s", limit)
    try:
        client = AsyncOpenDotaClient.get_instance()
        data = await client.get("leagues")

        if isinstance(data, dict) and "error" in data:
            logger.warning("get_leagues: API returned error: %s", data['error'])
            return f"❌ API 错误: {data['error']}"

        if not isinstance(data, list):
            logger.warning("get_leagues: unexpected data type=%s", type(data).__name__)
            return "❌ 获取联赛列表失败"

        logger.info("get_leagues: fetched %d items", len(data))

        leagues = data[:limit]

        lines = [
            "# 🏆 联赛列表",
            "",
            "| 联赛ID | 名称 | 等级 |",
            "|--------|------|------|",
        ]

        for l in leagues:
            league_id = l.get("leagueid", "N/A")
            name = l.get("name", "Unknown")[:30]
            tier = l.get("tier", "N/A")

            lines.append(f"| {league_id} | {name} | {tier} |")

        result = "\n".join(lines)
        logger.info("get_leagues: completed, result_len=%d", len(result))
        return result
    except Exception as e:
        logger.error("get_leagues: failed: %s", e, exc_info=True)
        raise
