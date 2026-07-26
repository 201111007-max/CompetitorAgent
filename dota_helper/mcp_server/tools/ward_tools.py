"""眼位分析工具 — Ward analysis and visualization tools.

Converts the synchronous dota2_fastmcp.py implementations to async
FastMCP tools that use ``AsyncOpenDotaClient`` for API calls and
``asyncio.to_thread()`` for CPU-bound matplotlib/PIL operations.
"""

import asyncio
import base64
import html as html_mod
import json
import logging
import math
import os
import re
import time
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

from dota_helper.mcp_server.server import mcp
from dota_helper.mcp_server.helpers.opendota import OpenDotaClient
from dota_helper.mcp_server.helpers.hero_names import get_cn_name
from dota_helper.mcp_server.helpers.map_config import format_time_mmss
from dota_helper.mcp_server.helpers.ward_visualization import (
    WardDataExtractor,
    WardAnalyzer,
    build_ward_report_data,
    build_multi_match_region_summary,
)
from dota_helper.mcp_server.helpers.map_config import (
    load_region_template,
    match_region,
    match_region_with_distance,
    distance_to_bbox,
    distance_to_polygon,
    parse_tower_key,
    gaussian_blur,
)
from dota_helper.mcp_server.helpers.text_processing import normalize_report_fragment

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WARD_OUTPUT_DIR = "ward_analysis"


# ---------------------------------------------------------------------------
# Async hero-map helper
# ---------------------------------------------------------------------------


async def _build_hero_map(client: OpenDotaClient) -> Dict[int, str]:
    """Build hero-id -> English-name mapping via the async client."""
    logger.info("_build_hero_map: fetching hero list")
    heroes = await client.get_heroes()
    result = {
        h["id"]: h.get("localized_name", "Hero %s" % h["id"])
        for h in heroes
        if isinstance(h, dict) and "id" in h
    }
    logger.info("_build_hero_map: fetched %d heroes", len(result))
    return result


# ---------------------------------------------------------------------------
# 1. analyze_match_wards
# ---------------------------------------------------------------------------


@mcp.tool()
async def analyze_match_wards(
    match_id: int,
    generate_html: bool = True,
    generate_image: bool = True,
) -> str:
    """分析指定比赛的眼位数据，生成可视化图表和交互式网页

    Args:
        match_id: Dota 2 比赛ID
        generate_html: 是否生成交互式HTML页面，默认True
        generate_image: 已禁用，保留兼容参数

    Returns:
        眼位分析结果，包括统计数据、视野分析数据(JSON)和生成的文件路径
    """
    logger.info("analyze_match_wards called with: match_id=%s, generate_html=%s", match_id, generate_html)
    try:
        client = OpenDotaClient.get_instance()
        if client is None:
            logger.warning("analyze_match_wards: OpenDota client not initialized")
            return "❌ OpenDota 客户端未初始化"

        # Fetch match details
        match_data = await client.get("matches/%s" % match_id)

        if isinstance(match_data, dict) and "error" in match_data:
            logger.warning("analyze_match_wards: API returned error for match_id=%s: %s", match_id, match_data.get("error"))
            return "❌ API 错误: %s" % match_data["error"]

        if not match_data:
            logger.warning("analyze_match_wards: no match data for match_id=%s", match_id)
            return "❌ 无法获取比赛 %s 的数据" % match_id

        logger.info("analyze_match_wards: fetched match data for match_id=%s", match_id)

        # Extract ward data
        extractor = WardDataExtractor()
        if not extractor.extract_from_match(match_data):
            logger.warning("analyze_match_wards: no ward data extracted for match_id=%s", match_id)
            return "❌ 比赛 %s 无眼位数据（可能未解析或无观察者数据）" % match_id

        df_obs, df_sen = extractor.get_dataframes()

        if df_obs.empty and df_sen.empty:
            logger.warning("analyze_match_wards: empty dataframes for match_id=%s", match_id)
            return "❌ 比赛 %s 无眼位数据" % match_id

        logger.info("analyze_match_wards: extracted %d observer wards, %d sentry wards", len(df_obs), len(df_sen))

        # Team names
        radiant_name: str = match_data.get("radiant_name") or "天辉 Radiant"
        dire_name: str = match_data.get("dire_name") or "夜魇 Dire"

        # Build rosters
        hero_map = await _build_hero_map(client)
        radiant_players: List[Dict[str, Any]] = []
        dire_players: List[Dict[str, Any]] = []
        kill_events: List[Dict[str, Any]] = []

        for p in match_data.get("players", []):
            raw_hero_id = p.get("hero_id")
            hero_id = int(raw_hero_id) if raw_hero_id is not None else 0
            hero_en = hero_map.get(hero_id, "Hero %s" % hero_id)
            hero_cn = get_cn_name(hero_en)
            player_name = p.get("name") or p.get("personaname") or p.get("account_id") or "Unknown"
            entry: Dict[str, Any] = {
                "hero_id": hero_id,
                "hero": hero_cn,
                "player": str(player_name),
            }
            is_radiant = p.get("isRadiant")
            if is_radiant is None:
                is_radiant = p.get("player_slot", 128) < 128 or p.get("is_radiant") == 1
            if is_radiant:
                radiant_players.append(entry)
            else:
                dire_players.append(entry)

            for kill in p.get("kills_log", []) or []:
                kill_events.append({
                    "time": int(kill.get("time", 0)),
                    "killer_team": "radiant" if is_radiant else "dire",
                    "killer_hero": hero_cn,
                    "killer_player": str(player_name),
                    "victim": kill.get("key"),
                })

        # Create analyzer
        match_duration = match_data.get("duration")
        analyzer = WardAnalyzer(
            df_obs,
            df_sen,
            radiant_name,
            dire_name,
            match_duration,
            radiant_players=radiant_players,
            dire_players=dire_players,
        )

        # Stats summary
        stats: str = analyzer.get_stats_summary()

        # Build report data
        tower_status: Dict[str, Optional[int]] = {
            "radiant": match_data.get("tower_status_radiant"),
            "dire": match_data.get("tower_status_dire"),
        }
        objectives = match_data.get("objectives", [])
        report_data = build_ward_report_data(
            df_obs,
            df_sen,
            radiant_name,
            dire_name,
            match_duration,
            radiant_players,
            dire_players,
            objectives=objectives,
            tower_status=tower_status,
            kill_events=kill_events,
        )
        report_data_json = json.dumps(report_data, ensure_ascii=False)

        # Ensure output dir
        if not os.path.exists(WARD_OUTPUT_DIR):
            os.makedirs(WARD_OUTPUT_DIR, exist_ok=True)

        generated_files: List[str] = []

        if generate_html:
            logger.info("analyze_match_wards: generating visualization for match_id=%s", match_id)
            html_path = os.path.join(WARD_OUTPUT_DIR, "ward_timeline_%s.html" % match_id)

            def _gen_html() -> bool:
                return analyzer.generate_interactive_html(html_path)

            logger.info("analyze_match_wards: running HTML generation in thread for match_id=%s", match_id)
            ok = await asyncio.to_thread(_gen_html)
            logger.info("analyze_match_wards: HTML generation thread completed for match_id=%s, ok=%s", match_id, ok)
            if ok:
                logger.info("analyze_match_wards: saved file %s", html_path)
                generated_files.append("🌐 交互式网页: %s" % html_path)
            else:
                logger.warning("analyze_match_wards: HTML generation failed for match_id=%s", match_id)
                generated_files.append("⚠️ 交互式网页生成失败")

        # Save CSV
        try:
            if not df_obs.empty:
                obs_csv_path = os.path.join(WARD_OUTPUT_DIR, "df_obs_%s.csv" % match_id)
                df_obs.to_csv(obs_csv_path, index=False)
                logger.info("analyze_match_wards: saved file %s", obs_csv_path)
                generated_files.append("📄 假眼数据: %s" % obs_csv_path)

            if not df_sen.empty:
                sen_csv_path = os.path.join(WARD_OUTPUT_DIR, "df_sen_%s.csv" % match_id)
                df_sen.to_csv(sen_csv_path, index=False)
                logger.info("analyze_match_wards: saved file %s", sen_csv_path)
                generated_files.append("📄 真眼数据: %s" % sen_csv_path)
        except Exception as e:
            logger.warning("analyze_match_wards: failed to save CSV for match_id=%s: %s", match_id, e)
            generated_files.append("⚠️ CSV保存失败: %s" % e)

        # Assemble result
        result = [
            "# 眼位分析 - 比赛 %s" % match_id,
            "",
            stats,
            "",
            "## 视野分析数据 (JSON)",
            "```json",
            report_data_json,
            "```",
            "",
            "## 生成的文件",
            "",
        ]
        result.extend(generated_files)

        logger.info("analyze_match_wards: completed for match_id=%s", match_id)
        return "\n".join(result)
    except Exception as e:
        logger.error("analyze_match_wards: failed for match_id=%s: %s", match_id, e, exc_info=True)
        return "❌ 分析失败: %s" % e


# ---------------------------------------------------------------------------
# 2. analyze_multi_match_wards
# ---------------------------------------------------------------------------


@mcp.tool()
async def analyze_multi_match_wards(
    match_ids: List[int],
    generate_html: bool = True,
    sigma: float = 5.0,
    alpha: float = 0.65,
    debug: bool = True,
) -> str:
    """获取多场比赛眼位/击杀/防御塔数据，并汇总生成热力图

    Args:
        match_ids: 指定比赛ID列表
        generate_html: 是否生成HTML页面，默认True
        sigma: 热力图高斯 sigma（0-128 坐标系单位）
        alpha: 热力图最大透明度（0-1）
        debug: 是否输出区域映射调试信息（输出到文件）

    Returns:
        汇总结果（包含 HTML/JSON 路径与统计摘要）
    """
    logger.info("analyze_multi_match_wards called with: match_ids=%s, generate_html=%s, sigma=%s, alpha=%s", match_ids, generate_html, sigma, alpha)
    client = OpenDotaClient.get_instance()
    if client is None:
        logger.warning("analyze_multi_match_wards: OpenDota client not initialized")
        return "❌ OpenDota 客户端未初始化"

    if not match_ids:
        logger.warning("analyze_multi_match_wards: empty match_ids")
        return "❌ 需要提供 match_ids"

    # Resolve match ids
    resolved_match_ids: List[int] = [int(mid) for mid in match_ids if mid is not None]
    logger.info("analyze_multi_match_wards: resolved %d match ids", len(resolved_match_ids))
    source_label: str = "custom"
    source_display: str = "custom"

    # Attempt to infer team identity for display naming
    team_presence_counts: Dict[int, int] = {}
    team_name_by_id: Dict[int, str] = {}

    obs_rows: List[Dict[str, Any]] = []
    sen_rows: List[Dict[str, Any]] = []
    obs_rows_radiant: List[Dict[str, Any]] = []
    obs_rows_dire: List[Dict[str, Any]] = []
    sen_rows_radiant: List[Dict[str, Any]] = []
    sen_rows_dire: List[Dict[str, Any]] = []
    kill_events: List[Dict[str, Any]] = []
    teamfight_events: List[Dict[str, Any]] = []
    tower_events: List[Dict[str, Any]] = []
    match_summaries: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    max_match_duration: int = 0
    max_ward_time: int = 0

    hero_map = await _build_hero_map(client)

    total = len(resolved_match_ids)
    for idx, mid in enumerate(resolved_match_ids, 1):
        logger.info("analyze_multi_match_wards: processing match %d/%d, match_id=%s", idx, total, mid)
        match_data = await client.get("matches/%s" % mid)
        if isinstance(match_data, dict) and "error" in match_data:
            logger.warning("analyze_multi_match_wards: API returned error for match_id=%s: %s", mid, match_data.get("error"))
            skipped.append({"match_id": mid, "reason": match_data.get("error")})
            continue

        if not match_data or not isinstance(match_data, dict):
            logger.warning("analyze_multi_match_wards: empty match data for match_id=%s", mid)
            skipped.append({"match_id": mid, "reason": "match data empty"})
            continue

        players = match_data.get("players", [])
        if not players:
            logger.warning("analyze_multi_match_wards: no players for match_id=%s", mid)
            skipped.append({"match_id": mid, "reason": "no players"})
            continue

        logger.info("analyze_multi_match_wards: fetched match data for match_id=%s", mid)

        radiant_label: str = match_data.get("radiant_name") or "Radiant"
        dire_label: str = match_data.get("dire_name") or "Dire"

        # Infer team identity from match data
        teams_in_match = set()
        for raw_tid, raw_name in (
            (match_data.get("radiant_team_id"), radiant_label),
            (match_data.get("dire_team_id"), dire_label),
        ):
            try:
                team_id_int = int(raw_tid) if raw_tid is not None else None
            except (TypeError, ValueError):
                team_id_int = None
            if team_id_int is None or team_id_int in teams_in_match:
                continue
            teams_in_match.add(team_id_int)
            team_presence_counts[team_id_int] = team_presence_counts.get(team_id_int, 0) + 1
            name_text = str(raw_name).strip() if raw_name else ""
            if name_text and name_text.lower() not in {"radiant", "dire", "天辉", "夜魇"}:
                team_name_by_id.setdefault(team_id_int, name_text)

        def _role_label(lane_role: Any) -> str:
            role_map: Dict[int, str] = {
                1: "优势路",
                2: "中路",
                3: "劣势路",
                4: "游走",
                5: "辅助",
            }
            try:
                role_key = int(lane_role)
            except (TypeError, ValueError):
                role_key = None
            return role_map.get(role_key, "未知")

        player_meta: List[Dict[str, str]] = []
        for p in players:
            player_slot = p.get("player_slot", 128)
            is_radiant = player_slot < 128
            player_meta.append({
                "team": radiant_label if is_radiant else dire_label,
                "role": _role_label(p.get("lane_role")),
            })

        match_duration = int(match_data.get("duration") or 0)
        if match_duration > max_match_duration:
            max_match_duration = match_duration

        obs_count = 0
        sen_count = 0
        obs_count_radiant = 0
        obs_count_dire = 0
        sen_count_radiant = 0
        sen_count_dire = 0
        kill_count = 0
        tower_count = 0

        for p in players:
            raw_hero_id = p.get("hero_id")
            hero_id = int(raw_hero_id) if raw_hero_id is not None else 0
            hero_en = hero_map.get(hero_id, f"Hero {hero_id}")
            hero_cn = get_cn_name(hero_en)
            player_name = p.get("name") or p.get("personaname") or p.get("account_id") or "Unknown"
            player_slot = p.get("player_slot", 128)
            is_radiant = player_slot < 128

            obs_left_map: Dict[int, int] = {}
            for left_entry in p.get("obs_left_log", []) or []:
                ehandle = left_entry.get("ehandle")
                if ehandle is None:
                    continue
                left_time = int(left_entry.get("time", 0))
                prev_time = obs_left_map.get(ehandle)
                if prev_time is None or left_time < prev_time:
                    obs_left_map[ehandle] = left_time
                if left_time > max_ward_time:
                    max_ward_time = left_time

            sen_left_map: Dict[int, int] = {}
            for left_entry in p.get("sen_left_log", []) or []:
                ehandle = left_entry.get("ehandle")
                if ehandle is None:
                    continue
                left_time = int(left_entry.get("time", 0))
                prev_time = sen_left_map.get(ehandle)
                if prev_time is None or left_time < prev_time:
                    sen_left_map[ehandle] = left_time
                if left_time > max_ward_time:
                    max_ward_time = left_time

            for ward in p.get("obs_log", []) or []:
                time_val = int(ward.get("time", 0))
                if time_val > max_ward_time:
                    max_ward_time = time_val
                ehandle = ward.get("ehandle")
                left_time = obs_left_map.get(ehandle) if ehandle is not None else None
                obs_entry: Dict[str, Any] = {
                    "match_id": mid,
                    "hero_id": hero_id,
                    "player": str(player_name),
                    "is_radiant": 1 if is_radiant else 0,
                    "time": time_val,
                    "x": float(ward.get("x", 0)),
                    "y": float(ward.get("y", 0)),
                    "ehandle": ehandle,
                    "left_time": left_time,
                }
                obs_rows.append(obs_entry)
                if is_radiant:
                    obs_rows_radiant.append(obs_entry)
                    obs_count_radiant += 1
                else:
                    obs_rows_dire.append(obs_entry)
                    obs_count_dire += 1
                obs_count += 1

            for ward in p.get("sen_log", []) or []:
                time_val = int(ward.get("time", 0))
                if time_val > max_ward_time:
                    max_ward_time = time_val
                ehandle = ward.get("ehandle")
                left_time = sen_left_map.get(ehandle) if ehandle is not None else None
                sen_entry: Dict[str, Any] = {
                    "match_id": mid,
                    "hero_id": hero_id,
                    "player": str(player_name),
                    "is_radiant": 1 if is_radiant else 0,
                    "time": time_val,
                    "x": float(ward.get("x", 0)),
                    "y": float(ward.get("y", 0)),
                    "ehandle": ehandle,
                    "left_time": left_time,
                }
                sen_rows.append(sen_entry)
                if is_radiant:
                    sen_rows_radiant.append(sen_entry)
                    sen_count_radiant += 1
                else:
                    sen_rows_dire.append(sen_entry)
                    sen_count_dire += 1
                sen_count += 1

            for kill in p.get("kills_log", []) or []:
                kill_events.append({
                    "match_id": mid,
                    "time": int(kill.get("time", 0)),
                    "killer_team": "radiant" if is_radiant else "dire",
                    "killer_hero": hero_cn,
                    "killer_player": str(player_name),
                    "victim": kill.get("key"),
                })
                kill_count += 1

        for teamfight in match_data.get("teamfights", []) or []:
            positions: List[Dict[str, Any]] = []
            for player_index, player_data in enumerate(teamfight.get("players", []) or []):
                deaths_pos = player_data.get("deaths_pos", {}) or {}
                if not isinstance(deaths_pos, dict):
                    continue
                meta = player_meta[player_index] if player_index < len(player_meta) else {}
                death_team = meta.get("team", "未知队伍")
                death_role = meta.get("role", "未知角色")
                for x_key, y_map in deaths_pos.items():
                    if not isinstance(y_map, dict):
                        continue
                    try:
                        x_val = int(x_key)
                    except (TypeError, ValueError):
                        continue
                    for y_key, count in y_map.items():
                        try:
                            y_val = int(y_key)
                        except (TypeError, ValueError):
                            continue
                        positions.append({
                            "x": x_val,
                            "y": y_val,
                            "count": int(count) if count is not None else 1,
                            "player_index": player_index,
                            "death_team": death_team,
                            "death_role": death_role,
                        })
            teamfight_events.append({
                "match_id": mid,
                "start": int(teamfight.get("start", 0)),
                "end": int(teamfight.get("end", 0)),
                "last_death": int(teamfight.get("last_death", 0)),
                "deaths": int(teamfight.get("deaths", 0)),
                "positions": positions,
                "target_side": "all",
                "own_label": radiant_label,
                "enemy_label": dire_label,
            })

        # Tower events
        objectives = match_data.get("objectives", [])
        for obj in objectives or []:
            if obj.get("type") != "building_kill":
                continue
            key = str(obj.get("key", ""))
            if "tower" not in key:
                continue
            info = parse_tower_key(key)
            tower_team = info.get("team")
            tower_events.append({
                "match_id": mid,
                "time": int(obj.get("time", 0)),
                "key": key,
                "tower_team": tower_team,
                "lane": info.get("lane"),
                "tier": info.get("tier"),
                "player_slot": obj.get("player_slot"),
            })
            tower_count += 1

        match_summaries.append({
            "match_id": mid,
            "radiant_name": match_data.get("radiant_name") or "Radiant",
            "dire_name": match_data.get("dire_name") or "Dire",
            "side": "all",
            "obs_count": obs_count,
            "sen_count": sen_count,
            "obs_count_radiant": obs_count_radiant,
            "sen_count_radiant": sen_count_radiant,
            "obs_count_dire": obs_count_dire,
            "sen_count_dire": sen_count_dire,
            "kill_count": kill_count,
            "tower_count": tower_count,
        })
        logger.info(
            "analyze_multi_match_wards: match_id=%s extracted %d observer wards, %d sentry wards",
            mid, obs_count, sen_count,
        )

    # Infer team name from match data
    if match_summaries and team_presence_counts:
        total_matches = len(match_summaries)
        best_team_id, best_count = max(
            team_presence_counts.items(),
            key=lambda item: item[1],
        )
        majority_threshold = max(2, (total_matches + 1) // 2)
        if best_count >= majority_threshold:
            source_label = f"team_{best_team_id}"
            inferred_name = team_name_by_id.get(best_team_id) or f"Team {best_team_id}"
            if best_count == total_matches:
                source_display = inferred_name
            else:
                source_display = f"{inferred_name}（主要样本 {best_count}/{total_matches} 场）"

    if not obs_rows and not sen_rows:
        logger.warning("analyze_multi_match_wards: no ward data collected from any match")
        return "❌ 未获取到目标眼位数据（可能比赛未解析或无观察者数据）"

    if max_match_duration <= 0:
        max_match_duration = 7200

    df_obs = pd.DataFrame(obs_rows) if obs_rows else pd.DataFrame()
    df_sen = pd.DataFrame(sen_rows) if sen_rows else pd.DataFrame()
    df_obs_radiant = pd.DataFrame(obs_rows_radiant) if obs_rows_radiant else pd.DataFrame()
    df_sen_radiant = pd.DataFrame(sen_rows_radiant) if sen_rows_radiant else pd.DataFrame()
    df_obs_dire = pd.DataFrame(obs_rows_dire) if obs_rows_dire else pd.DataFrame()
    df_sen_dire = pd.DataFrame(sen_rows_dire) if sen_rows_dire else pd.DataFrame()

    # ------------------------------------------------------------------
    # Heatmap & image generation (CPU-bound → run in thread)
    # ------------------------------------------------------------------

    logger.info("analyze_multi_match_wards: generating visualization in thread")

    def _generate_visuals() -> Tuple[
        str, str, str, str, str, str, str
    ]:
        """Run all CPU-bound matplotlib/PIL operations synchronously."""
        analyzer_radiant = WardAnalyzer(
            df_obs_radiant,
            df_sen_radiant,
            radiant_name="天辉 Radiant",
            dire_name="夜魇 Dire",
            match_duration=None,
            radiant_players=[],
            dire_players=[],
        )
        analyzer_dire = WardAnalyzer(
            df_obs_dire,
            df_sen_dire,
            radiant_name="天辉 Radiant",
            dire_name="夜魇 Dire",
            match_duration=None,
            radiant_players=[],
            dire_players=[],
        )

        points_base64_radiant = analyzer_radiant._generate_ward_points_base64()
        heatmap_base64_radiant_obs = analyzer_radiant._generate_heatmap_base64(
            sigma=sigma, alpha=alpha, ward_type="obs",
        )
        heatmap_base64_radiant_sen = analyzer_radiant._generate_heatmap_base64(
            sigma=sigma, alpha=alpha, ward_type="sen",
        )
        points_base64_dire = analyzer_dire._generate_ward_points_base64()
        heatmap_base64_dire_obs = analyzer_dire._generate_heatmap_base64(
            sigma=sigma, alpha=alpha, ward_type="obs",
        )
        heatmap_base64_dire_sen = analyzer_dire._generate_heatmap_base64(
            sigma=sigma, alpha=alpha, ward_type="sen",
        )

        map_base64 = ""
        if analyzer_radiant.map_image:
            buffered = BytesIO()
            analyzer_radiant.map_image.save(buffered, format="JPEG")
            map_base64 = base64.b64encode(buffered.getvalue()).decode()

        return (
            points_base64_radiant,
            heatmap_base64_radiant_obs,
            heatmap_base64_radiant_sen,
            heatmap_base64_dire_obs,
            heatmap_base64_dire_sen,
            points_base64_dire,
            map_base64,
        )

    (
        _points_b64_radiant,
        heatmap_base64_radiant_obs,
        heatmap_base64_radiant_sen,
        heatmap_base64_dire_obs,
        heatmap_base64_dire_sen,
        _points_b64_dire,
        map_base64,
    ) = await asyncio.to_thread(_generate_visuals)
    logger.info("analyze_multi_match_wards: visualization generation thread completed")

    # ------------------------------------------------------------------
    # Statistics (no heavy CPU, can stay on event loop)
    # ------------------------------------------------------------------

    total_obs = len(df_obs) if not df_obs.empty else 0
    total_sen = len(df_sen) if not df_sen.empty else 0
    total_obs_radiant = len(df_obs_radiant) if not df_obs_radiant.empty else 0
    total_sen_radiant = len(df_sen_radiant) if not df_sen_radiant.empty else 0
    total_obs_dire = len(df_obs_dire) if not df_obs_dire.empty else 0
    total_sen_dire = len(df_sen_dire) if not df_sen_dire.empty else 0
    total_kills = len(kill_events)
    total_towers = len(tower_events)
    region_summary, region_template = build_multi_match_region_summary(obs_rows, sen_rows)

    # Ward lifetime stats
    def _ward_lifetime_stats(
        rows: List[Dict[str, Any]], default_duration: int,
    ) -> Dict[str, Any]:
        durations: List[int] = []
        for ward in rows:
            try:
                time_val = int(ward.get("time", 0) or 0)
            except (TypeError, ValueError):
                time_val = 0
            left_raw = ward.get("left_time")
            duration = None
            if left_raw is not None:
                try:
                    left_time = int(left_raw)
                except (TypeError, ValueError):
                    left_time = None
                if left_time is not None and left_time >= time_val:
                    duration = left_time - time_val
            if duration is None:
                duration = default_duration
            if duration >= 0:
                durations.append(int(duration))
        if not durations:
            return {"count": 0, "avg": None, "median": None, "min": None, "max": None}
        return {
            "count": len(durations),
            "avg": sum(durations) / len(durations),
            "median": float(np.median(durations)),
            "min": min(durations),
            "max": max(durations),
        }

    ward_lifetime: Dict[str, Any] = {
        "obs": _ward_lifetime_stats(obs_rows, 360),
        "sen": _ward_lifetime_stats(sen_rows, 420),
        "by_side": {
            "radiant": {
                "obs": _ward_lifetime_stats(obs_rows_radiant, 360),
                "sen": _ward_lifetime_stats(sen_rows_radiant, 420),
            },
            "dire": {
                "obs": _ward_lifetime_stats(obs_rows_dire, 360),
                "sen": _ward_lifetime_stats(sen_rows_dire, 420),
            },
        },
    }

    # Region lifetime summary
    def _region_lifetime_summary(
        obs_rows_src: List[Dict[str, Any]],
        sen_rows_src: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        regions = load_region_template()
        region_map: Dict[Tuple[str, str], Dict[str, Any]] = {}

        def _duration_seconds(row: Dict[str, Any], dd: int) -> Optional[int]:
            try:
                time_val = int(row.get("time", 0) or 0)
            except (TypeError, ValueError):
                time_val = 0
            left_raw = row.get("left_time")
            duration_val = None
            if left_raw is not None:
                try:
                    left_time = int(left_raw)
                except (TypeError, ValueError):
                    left_time = None
                if left_time is not None and left_time >= time_val:
                    duration_val = left_time - time_val
            if duration_val is None:
                duration_val = dd
            return duration_val if duration_val >= 0 else None

        def _is_killed(row: Dict[str, Any], max_duration: int) -> bool:
            try:
                time_val = int(row.get("time", 0) or 0)
            except (TypeError, ValueError):
                time_val = 0
            left_raw = row.get("left_time")
            if left_raw is None:
                return False
            try:
                left_time = int(left_raw)
            except (TypeError, ValueError):
                return False
            return left_time < time_val + max_duration

        def _collect(rows: List[Dict[str, Any]], ward_type: str, dd: int) -> None:
            for row in rows:
                x = row.get("x")
                y = row.get("y")
                if x is None or y is None:
                    continue
                try:
                    x_val = float(x)
                    y_val = float(y)
                except (TypeError, ValueError):
                    continue
                primary_key, primary_label, _labels = match_region(x_val, y_val, regions)
                label = primary_label or "未知区域"
                duration_val = _duration_seconds(row, dd)
                if duration_val is None:
                    continue
                killed = _is_killed(row, dd)
                is_early_kill = killed and duration_val <= 120
                is_full_survival = not killed or duration_val >= dd
                ratio_val = min(duration_val, dd) / dd
                rk = (label, ward_type)
                entry = region_map.setdefault(rk, {
                    "label": label,
                    "type": ward_type,
                    "key": primary_key,
                    "durations": [],
                    "early_kill_count": 0,
                    "full_survival_count": 0,
                    "ratio_sum": 0.0,
                })
                entry["durations"].append(int(duration_val))
                entry["early_kill_count"] += 1 if is_early_kill else 0
                entry["full_survival_count"] += 1 if is_full_survival else 0
                entry["ratio_sum"] += ratio_val

        _collect(obs_rows_src, "obs", 360)
        _collect(sen_rows_src, "sen", 420)

        summary: List[Dict[str, Any]] = []
        for entry in region_map.values():
            durations = entry.get("durations", [])
            if not durations:
                stats_d = {
                    "count": 0,
                    "avg": None,
                    "median": None,
                    "min": None,
                    "max": None,
                    "early_kill_rate": None,
                    "full_survival_rate": None,
                    "avg_time_survival_ratio": None,
                }
            else:
                stats_d = {
                    "count": len(durations),
                    "avg": sum(durations) / len(durations),
                    "median": float(np.median(durations)),
                    "min": min(durations),
                    "max": max(durations),
                    "early_kill_rate": entry.get("early_kill_count", 0) / len(durations),
                    "full_survival_rate": entry.get("full_survival_count", 0) / len(durations),
                    "avg_time_survival_ratio": entry.get("ratio_sum", 0.0) / len(durations),
                }
            summary.append({
                "label": entry.get("label"),
                "type": entry.get("type"),
                "key": entry.get("key"),
                **stats_d,
            })

        summary.sort(key=lambda x: x.get("count", 0), reverse=True)
        return summary

    ward_lifetime_by_region = _region_lifetime_summary(obs_rows, sen_rows)

    # Output dirs
    if not os.path.exists(WARD_OUTPUT_DIR):
        os.makedirs(WARD_OUTPUT_DIR, exist_ok=True)

    timestamp = int(time.time())
    html_path = os.path.join(WARD_OUTPUT_DIR, f"ward_multi_{source_label}_{timestamp}.html")
    json_path = os.path.join(WARD_OUTPUT_DIR, f"ward_multi_{source_label}_{timestamp}.json")

    # Payload
    output_payload: Dict[str, Any] = {
        "source": source_display,
        "source_id": source_label,
        "matches": match_summaries,
        "totals": {
            "obs": total_obs,
            "sen": total_sen,
            "kills": total_kills,
            "tower_kills": total_towers,
            "by_side": {
                "radiant": {"obs": total_obs_radiant, "sen": total_sen_radiant},
                "dire": {"obs": total_obs_dire, "sen": total_sen_dire},
            },
        },
        "wards": {
            "obs": obs_rows,
            "sen": sen_rows,
            "by_side": {
                "radiant": {"obs": obs_rows_radiant, "sen": sen_rows_radiant},
                "dire": {"obs": obs_rows_dire, "sen": sen_rows_dire},
            },
        },
        "region_template": region_template,
        "region_summary": region_summary,
        "ward_lifetime": ward_lifetime,
        "ward_lifetime_by_region": ward_lifetime_by_region,
        "kills": kill_events,
        "teamfights": teamfight_events,
        "tower_events": tower_events,
        "skipped": skipped,
    }

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(output_payload, f, ensure_ascii=False, indent=2)
        logger.info("analyze_multi_match_wards: saved file %s", json_path)
    except Exception as e:
        logger.warning("analyze_multi_match_wards: failed to save file %s: %s", json_path, e)

    # ------------------------------------------------------------------
    # HTML generation helpers
    # ------------------------------------------------------------------

    rows_html = "\n".join(
        f"<tr><td>{m['match_id']}</td><td>{html_mod.escape(m['radiant_name'])} vs {html_mod.escape(m['dire_name'])}</td>"
        f"<td>{m['side']}</td>"
        f"<td>{m.get('obs_count_radiant', 0)}/{m.get('sen_count_radiant', 0)}</td>"
        f"<td>{m.get('obs_count_dire', 0)}/{m.get('sen_count_dire', 0)}</td>"
        f"<td>{m['kill_count']}</td><td>{m['tower_count']}</td></tr>"
        for m in match_summaries
    )
    if not rows_html:
        rows_html = "<tr><td colspan=\"7\">暂无数据</td></tr>"

    total_radiant_side = total_obs_radiant + total_sen_radiant
    total_dire_side = total_obs_dire + total_sen_dire

    def _format_ratio(value: int, total: int) -> str:
        if total <= 0:
            return "-"
        return f"{value / total * 100:.1f}%"

    def _format_time(seconds: int) -> str:
        if seconds is None:
            return "-"
        try:
            sec_val = int(seconds)
        except (TypeError, ValueError):
            return "-"
        sign = "-" if sec_val < 0 else ""
        sec_val = abs(sec_val)
        return f"{sign}{sec_val // 60}:{sec_val % 60:02d}"

    def _format_duration(value: Optional[float]) -> str:
        if value is None:
            return "-"
        try:
            sec_val = int(round(float(value)))
        except (TypeError, ValueError):
            return "-"
        minutes, secs = divmod(max(sec_val, 0), 60)
        return f"{minutes}:{secs:02d}"

    def _format_percent(value: Optional[float]) -> str:
        if value is None:
            return "-"
        try:
            return f"{float(value) * 100:.1f}%"
        except (TypeError, ValueError):
            return "-"

    def _format_ratio_value(value: Optional[float]) -> str:
        if value is None:
            return "-"
        try:
            return f"{float(value) * 100:.1f}%"
        except (TypeError, ValueError):
            return "-"

    debug_lines: List[str] = []

    def _debug_log(message: str) -> None:
        if debug:
            debug_lines.append(message)

    region_radiant = sorted(
        region_summary,
        key=lambda r: int(r.get("obs_radiant", 0)) + int(r.get("sen_radiant", 0)),
        reverse=True,
    )
    region_dire = sorted(
        region_summary,
        key=lambda r: int(r.get("obs_dire", 0)) + int(r.get("sen_dire", 0)),
        reverse=True,
    )

    region_rows_radiant_html = "\n".join(
        "<tr>"
        f"<td>{html_mod.escape(str(r.get('label', '')))}</td>"
        f"<td>{r.get('obs_radiant', 0)}</td>"
        f"<td>{r.get('sen_radiant', 0)}</td>"
        f"<td>{int(r.get('obs_radiant', 0)) + int(r.get('sen_radiant', 0))}</td>"
        f"<td>{_format_ratio(int(r.get('obs_radiant', 0)) + int(r.get('sen_radiant', 0)), total_radiant_side)}</td>"
        "</tr>"
        for r in region_radiant
        if int(r.get("obs_radiant", 0)) + int(r.get("sen_radiant", 0)) > 0
    )
    if not region_rows_radiant_html:
        region_rows_radiant_html = "<tr><td colspan=\"5\">暂无数据</td></tr>"

    region_rows_dire_html = "\n".join(
        "<tr>"
        f"<td>{html_mod.escape(str(r.get('label', '')))}</td>"
        f"<td>{r.get('obs_dire', 0)}</td>"
        f"<td>{r.get('sen_dire', 0)}</td>"
        f"<td>{int(r.get('obs_dire', 0)) + int(r.get('sen_dire', 0))}</td>"
        f"<td>{_format_ratio(int(r.get('obs_dire', 0)) + int(r.get('sen_dire', 0)), total_dire_side)}</td>"
        "</tr>"
        for r in region_dire
        if int(r.get("obs_dire", 0)) + int(r.get("sen_dire", 0)) > 0
    )
    if not region_rows_dire_html:
        region_rows_dire_html = "<tr><td colspan=\"5\">暂无数据</td></tr>"

    def _region_lifetime_row(item: Dict[str, Any]) -> str:
        return (
            "<tr>"
            f"<td>{html_mod.escape(str(item.get('label', '')))}</td>"
            f"<td>{item.get('count', 0)}</td>"
            f"<td>{_format_duration(item.get('avg'))}</td>"
            f"<td>{_format_duration(item.get('median'))}</td>"
            f"<td>{_format_duration(item.get('min'))}</td>"
            f"<td>{_format_duration(item.get('max'))}</td>"
            f"<td>{_format_percent(item.get('early_kill_rate'))}</td>"
            f"<td>{_format_percent(item.get('full_survival_rate'))}</td>"
            f"<td>{_format_ratio_value(item.get('avg_time_survival_ratio'))}</td>"
            "</tr>"
        )

    if ward_lifetime_by_region:
        obs_rows_html_inner = "\n".join(
            _region_lifetime_row(item)
            for item in ward_lifetime_by_region
            if item.get("type") == "obs"
        )
        sen_rows_html_inner = "\n".join(
            _region_lifetime_row(item)
            for item in ward_lifetime_by_region
            if item.get("type") == "sen"
        )
        ward_lifetime_obs_rows_html = obs_rows_html_inner or "<tr><td colspan=\"9\">暂无数据</td></tr>"
        ward_lifetime_sen_rows_html = sen_rows_html_inner or "<tr><td colspan=\"9\">暂无数据</td></tr>"
    else:
        ward_lifetime_obs_rows_html = "<tr><td colspan=\"9\">暂无数据</td></tr>"
        ward_lifetime_sen_rows_html = "<tr><td colspan=\"9\">暂无数据</td></tr>"

    region_note = ""
    if not region_template:
        region_note = '<div class="summary">⚠️ 未加载区域模板，可能全部落入"未知区域"。</div>'

    # Region → match/ward mapping for teamfight vision analysis
    regions = load_region_template()
    region_lookup: Dict[str, Dict[str, Any]] = {
        str(r.get("key") or r.get("label")): r for r in (regions or [])
    }
    obs_by_match_region: Dict[int, List[Dict[str, Any]]] = {}
    sen_by_match_region: Dict[int, List[Dict[str, Any]]] = {}
    if regions:
        for obs in obs_rows:
            try:
                x_val = float(obs.get("x", 0))
                y_val = float(obs.get("y", 0))
            except (TypeError, ValueError):
                continue
            region_key, region_label, _ = match_region(x_val, y_val, regions)
            if not region_key:
                _debug_log(
                    f"[OBS_MAP] match={obs.get('match_id')} time={obs.get('time')} "
                    f"x={x_val} y={y_val} -> region=未知区域"
                )
                continue
            start_time = int(obs.get("time", 0) or 0)
            left_raw = obs.get("left_time")
            end_time = None
            if left_raw is not None:
                try:
                    end_candidate = int(left_raw)
                except (TypeError, ValueError):
                    end_candidate = None
                if end_candidate is not None and end_candidate >= start_time:
                    end_time = end_candidate
            if end_time is None:
                end_time = start_time + 360
            match_id_val = int(obs.get("match_id", 0) or 0)
            obs_by_match_region.setdefault(match_id_val, []).append({
                "region_key": region_key,
                "region_label": region_label,
                "start": start_time,
                "end": end_time,
                "x": x_val,
                "y": y_val,
            })
            _debug_log(
                f"[OBS_MAP] match={match_id_val} time={start_time} x={x_val} y={y_val} "
                f"-> region={region_label}/{region_key} end={end_time}"
            )
        for sen in sen_rows:
            try:
                x_val = float(sen.get("x", 0))
                y_val = float(sen.get("y", 0))
            except (TypeError, ValueError):
                continue
            region_key, region_label, _ = match_region(x_val, y_val, regions)
            if not region_key:
                _debug_log(
                    f"[SEN_MAP] match={sen.get('match_id')} time={sen.get('time')} "
                    f"x={x_val} y={y_val} -> region=未知区域"
                )
                continue
            start_time = int(sen.get("time", 0) or 0)
            left_raw = sen.get("left_time")
            end_time = None
            if left_raw is not None:
                try:
                    end_candidate = int(left_raw)
                except (TypeError, ValueError):
                    end_candidate = None
                if end_candidate is not None and end_candidate >= start_time:
                    end_time = end_candidate
            if end_time is None:
                end_time = start_time + 420
            match_id_val = int(sen.get("match_id", 0) or 0)
            sen_by_match_region.setdefault(match_id_val, []).append({
                "region_key": region_key,
                "region_label": region_label,
                "start": start_time,
                "end": end_time,
                "x": x_val,
                "y": y_val,
            })
            _debug_log(
                f"[SEN_MAP] match={match_id_val} time={start_time} x={x_val} y={y_val} "
                f"-> region={region_label}/{region_key} end={end_time}"
            )

    def _resolve_teamfight_region(
        x_val: float,
        y_val: float,
        region_items: List[Dict[str, Any]],
    ) -> Tuple[Optional[str], Optional[str], float, float, str]:
        region_key, region_label, _labels, raw_dist, _ = match_region_with_distance(
            x_val, y_val, region_items, allow_nearest=True,
        )
        shifted_x = x_val + 64
        shifted_y = y_val + 64
        region_key_shift, region_label_shift, _labels_shift, shift_dist, _ = match_region_with_distance(
            shifted_x, shifted_y, region_items, allow_nearest=True,
        )
        if raw_dist <= shift_dist:
            return region_key, region_label, x_val, y_val, "raw"
        return region_key_shift, region_label_shift, shifted_x, shifted_y, "shifted"

    def _distance_to_region(x_val: float, y_val: float, region: Optional[Dict[str, Any]]) -> float:
        if not region:
            return float("inf")
        min_dist = float("inf")
        for area in region.get("areas", []):
            area_type = area.get("type")
            if area_type == "bbox":
                dist = distance_to_bbox(x_val, y_val, area)
            elif area_type == "polygon":
                points = area.get("points") or []
                dist = distance_to_polygon(x_val, y_val, points)
            else:
                continue
            if dist < min_dist:
                min_dist = dist
        return min_dist

    def _ward_active(ward: Dict[str, Any], window_start: int, window_end: int) -> bool:
        try:
            start_time = int(ward.get("start", 0) or 0)
        except (TypeError, ValueError):
            start_time = 0
        try:
            end_time = int(ward.get("end", 0) or 0)
        except (TypeError, ValueError):
            end_time = 0
        return start_time <= window_end and end_time >= window_start

    def _pick_primary_region(positions: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
        region_weights: Dict[str, int] = {}
        region_labels_map: Dict[str, str] = {}
        for pos in positions:
            region_key = pos.get("region_key")
            region_label = pos.get("region_label") or "未知区域"
            if not region_key:
                continue
            weight = int(pos.get("count", 1) or 1)
            region_weights[region_key] = region_weights.get(region_key, 0) + weight
            region_labels_map[region_key] = region_label
        if not region_weights:
            return None, None
        primary_key = max(region_weights.items(), key=lambda item: item[1])[0]
        return primary_key, region_labels_map.get(primary_key)

    for teamfight in teamfight_events:
        tf_match_id = int(teamfight.get("match_id", 0) or 0)
        tf_start = int(teamfight.get("start", 0) or 0)
        tf_end = int(teamfight.get("end", tf_start) or tf_start)
        last_death = int(teamfight.get("last_death", tf_end) or tf_end)
        if tf_end < tf_start and last_death >= tf_start:
            tf_end = last_death
        obs_candidates = obs_by_match_region.get(tf_match_id, [])
        positions = teamfight.get("positions", []) or []
        enriched_positions: List[Dict[str, Any]] = []
        positions_with_obs = 0
        for pos in positions:
            try:
                pos_x = float(pos.get("x", 0))
                pos_y = float(pos.get("y", 0))
            except (TypeError, ValueError):
                continue
            if regions:
                region_key, region_label, map_x, map_y, map_mode = _resolve_teamfight_region(pos_x, pos_y, regions)
            else:
                region_key, region_label, map_x, map_y, map_mode = None, None, pos_x, pos_y, "none"
            _debug_log(
                f"[TF_MAP] match={tf_match_id} tf={tf_start}-{tf_end} "
                f"raw=({pos_x},{pos_y}) mapped=({map_x},{map_y}) mode={map_mode} "
                f"region={region_label or '未知区域'}/{region_key or 'None'}"
            )
            obs_count = 0
            if region_key:
                for ward in obs_candidates:
                    if ward.get("region_key") != region_key:
                        continue
                    if ward.get("start", 0) <= tf_end and ward.get("end", 0) > tf_start:
                        obs_count += 1
                if obs_count > 0:
                    positions_with_obs += 1
            enriched_positions.append({
                **pos,
                "map_x": map_x,
                "map_y": map_y,
                "region_key": region_key,
                "region_label": region_label or "未知区域",
                "obs_count": obs_count,
                "has_obs": obs_count > 0,
            })
        if not enriched_positions:
            continue

        teamfight["positions"] = enriched_positions
        teamfight["positions_total"] = len(enriched_positions)
        teamfight["positions_with_obs"] = positions_with_obs

        fight_region_key, fight_region_label = _pick_primary_region(enriched_positions)
        if not fight_region_label:
            fight_region_label = "未知区域"

        window_end = tf_start
        window_start = max(0, tf_start - 10)
        wards_in_match = obs_by_match_region.get(tf_match_id, []) + sen_by_match_region.get(tf_match_id, [])
        offensive_vision = "无"
        if fight_region_key:
            has_direct = False
            for ward in wards_in_match:
                if not _ward_active(ward, window_start, window_end):
                    continue
                if ward.get("region_key") == fight_region_key:
                    has_direct = True
                    break
            if has_direct:
                offensive_vision = "有"
            else:
                fight_region = region_lookup.get(fight_region_key)
                if fight_region:
                    for ward in wards_in_match:
                        if not _ward_active(ward, window_start, window_end):
                            continue
                        try:
                            ward_x = float(ward.get("x", 0))
                            ward_y = float(ward.get("y", 0))
                        except (TypeError, ValueError):
                            continue
                        if _distance_to_region(ward_x, ward_y, fight_region) <= 8.0:
                            offensive_vision = "部分"
                            break
        elif enriched_positions:
            total_weight = sum(int(p.get("count", 1) or 1) for p in enriched_positions)
            if total_weight > 0:
                cx = sum(float(p.get("map_x", p.get("x", 0))) * int(p.get("count", 1) or 1) for p in enriched_positions) / total_weight
                cy = sum(float(p.get("map_y", p.get("y", 0))) * int(p.get("count", 1) or 1) for p in enriched_positions) / total_weight
                for ward in wards_in_match:
                    if not _ward_active(ward, window_start, window_end):
                        continue
                    try:
                        ward_x = float(ward.get("x", 0))
                        ward_y = float(ward.get("y", 0))
                    except (TypeError, ValueError):
                        continue
                    if math.hypot(ward_x - cx, ward_y - cy) <= 8.0:
                        offensive_vision = "部分"
                        break

        own_label = teamfight.get("own_label") or ""
        enemy_label = teamfight.get("enemy_label") or ""
        own_deaths = 0
        enemy_deaths = 0
        for pos in enriched_positions:
            count_val = int(pos.get("count", 1) or 1)
            death_team = pos.get("death_team")
            if death_team == own_label:
                own_deaths += count_val
            elif death_team == enemy_label:
                enemy_deaths += count_val

        if not fight_region_key or (enemy_deaths + own_deaths) == 0:
            continue

        kill_diff = enemy_deaths - own_deaths
        if kill_diff > 0:
            fight_result = "✅ 胜"
        elif kill_diff < 0:
            fight_result = "❌ 败"
        else:
            fight_result = "⚖ 平"

        teamfight["region_key"] = fight_region_key
        teamfight["region_label"] = fight_region_label
        teamfight["offensive_vision"] = offensive_vision
        teamfight["enemy_deaths"] = enemy_deaths
        teamfight["own_deaths"] = own_deaths
        teamfight["kill_diff"] = kill_diff
        teamfight["result"] = fight_result

    def _format_positions_html(positions: List[Dict[str, Any]]) -> str:
        if not positions:
            return "暂无"
        return "<br/>".join(
            f"{pos.get('region_label', '未知区域')} {pos.get('map_x', pos.get('x'))},{pos.get('map_y', pos.get('y'))}×{pos.get('count', 1)}"
            f" ({'有假眼' if pos.get('has_obs') else '无假眼'})"
            f" - {pos.get('death_team', '未知队伍')}/{pos.get('death_role', '未知角色')}"
            for pos in positions
        )

    def _format_kill_diff(value: int) -> str:
        if value > 0:
            return f"+{value}"
        return str(value)

    def _format_death_value(value: int) -> str:
        return "0" if value == 0 else str(value)

    def _is_valid_teamfight_row(tf: Dict[str, Any]) -> bool:
        label = str(tf.get("region_label") or "").strip()
        if not label or label == "未知区域":
            return False
        if int(tf.get("enemy_deaths", 0) or 0) + int(tf.get("own_deaths", 0) or 0) == 0:
            return False
        return True

    valid_teamfights = [tf for tf in teamfight_events if _is_valid_teamfight_row(tf)]

    teamfight_rows_html = "\n".join(
        "<tr>"
        f"<td>{tf.get('match_id')}</td>"
        f"<td>{_format_time(tf.get('start'))} - {_format_time(tf.get('end'))}</td>"
        f"<td>{html_mod.escape(str(tf.get('region_label') or '未知区域'))}</td>"
        f"<td>{html_mod.escape(str(tf.get('offensive_vision') or '无'))}</td>"
        f"<td>{_format_death_value(int(tf.get('enemy_deaths', 0) or 0))}</td>"
        f"<td>{_format_death_value(int(tf.get('own_deaths', 0) or 0))}</td>"
        f"<td>{_format_kill_diff(int(tf.get('kill_diff', 0) or 0))}</td>"
        f"<td>{html_mod.escape(str(tf.get('result') or ''))}</td>"
        "</tr>"
        for tf in valid_teamfights
    )
    if not teamfight_rows_html:
        teamfight_rows_html = "<tr><td colspan=\"8\">暂无数据</td></tr>"

    vision_buckets: Dict[str, List[Dict[str, Any]]] = {
        "有": [],
        "部分": [],
        "无": [],
    }
    for tf in valid_teamfights:
        vision = tf.get("offensive_vision") or "无"
        if vision not in vision_buckets:
            vision = "无"
        vision_buckets[vision].append(tf)

    def _avg_or_dash(values: List[int]) -> str:
        if not values:
            return "-"
        return f"{sum(values) / len(values):.1f}"

    def _win_rate_or_dash(values: List[int]) -> str:
        if not values:
            return "-"
        wins = sum(1 for v in values if v > 0)
        return f"{wins / len(values) * 100:.0f}%"

    teamfight_summary_rows_html = "\n".join(
        "<tr>"
        f"<td>{html_mod.escape(label)}</td>"
        f"<td>{len(items)}</td>"
        f"<td>{_avg_or_dash([int(i.get('enemy_deaths', 0) or 0) for i in items])}</td>"
        f"<td>{_avg_or_dash([int(i.get('own_deaths', 0) or 0) for i in items])}</td>"
        f"<td>{_avg_or_dash([int(i.get('kill_diff', 0) or 0) for i in items])}</td>"
        f"<td>{_win_rate_or_dash([int(i.get('kill_diff', 0) or 0) for i in items])}</td>"
        "</tr>"
        for label, items in [("有", vision_buckets["有"]), ("部分", vision_buckets["部分"]), ("无", vision_buckets["无"])]
    )
    if not teamfight_summary_rows_html:
        teamfight_summary_rows_html = "<tr><td colspan=\"6\">暂无数据</td></tr>"

    # Icon base64 for HTML
    icon_base64: Dict[str, str] = {}
    icon_dir = "figure"
    icon_files = {
        "obs_radiant": "goodguys_observer.png",
        "obs_dire": "badguys_observer.png",
        "sen_radiant": "goodguys_sentry.png",
        "sen_dire": "badguys_sentry.png",
    }
    for key, filename in icon_files.items():
        icon_path = os.path.join(icon_dir, filename)
        if os.path.exists(icon_path):
            try:
                with open(icon_path, "rb") as f:
                    icon_base64[key] = base64.b64encode(f.read()).decode()
            except Exception:
                pass

    hero_cn_cache: Dict[int, str] = {}

    def _hero_cn(hero_id: int) -> str:
        if hero_id not in hero_cn_cache:
            hero_en = hero_map.get(hero_id, f"Hero {hero_id}")
            hero_cn_cache[hero_id] = get_cn_name(hero_en)
        return hero_cn_cache[hero_id]

    def _build_ward_points(
        rows: List[Dict[str, Any]],
        icon_key: str,
        is_obs: bool,
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for ward in rows:
            try:
                x_val = float(ward.get("x", 0)) - 64
                y_val = float(ward.get("y", 0)) - 64
            except (TypeError, ValueError):
                continue
            if not (np.isfinite(x_val) and np.isfinite(y_val)):
                continue
            x_val = float(np.clip(x_val, 0, 128))
            y_val = float(np.clip(y_val, 0, 128))
            time_val = int(ward.get("time", 0) or 0)
            end_time = None
            left_raw = ward.get("left_time")
            if left_raw is not None:
                try:
                    end_time_val = int(left_raw)
                except (TypeError, ValueError):
                    end_time_val = None
                if end_time_val is not None:
                    if end_time_val >= time_val:
                        end_time = end_time_val
            if end_time is None:
                default_duration = 360 if is_obs else 420
                end_time = time_val + default_duration
            hero_id = int(ward.get("hero_id", 0) or 0)
            items.append({
                "x": x_val,
                "y": y_val,
                "time": time_val,
                "end_time": end_time,
                "type": icon_key,
                "is_obs": is_obs,
                "hero": _hero_cn(hero_id),
                "player": str(ward.get("player", "Unknown")),
                "match_id": ward.get("match_id"),
            })
        return items

    wards_radiant_data: List[Dict[str, Any]] = []
    wards_radiant_data.extend(_build_ward_points(obs_rows_radiant, "obs_radiant", True))
    wards_radiant_data.extend(_build_ward_points(sen_rows_radiant, "sen_radiant", False))
    wards_dire_data: List[Dict[str, Any]] = []
    wards_dire_data.extend(_build_ward_points(obs_rows_dire, "obs_dire", True))
    wards_dire_data.extend(_build_ward_points(sen_rows_dire, "sen_dire", False))
    total_points_radiant = len(wards_radiant_data)
    total_points_dire = len(wards_dire_data)
    player_list = sorted({
        str(w.get("player", "Unknown")) for w in (wards_radiant_data + wards_dire_data)
    })
    if player_list:
        player_filter_html = "\n".join(
            f"<label class=\"filter-item\"><input type=\"checkbox\" name=\"playerFilter\" "
            f"value=\"{html_mod.escape(player)}\" checked> {html_mod.escape(player)}</label>"
            for player in player_list
        )
    else:
        player_filter_html = "<div class=\"placeholder\">暂无选手数据</div>"

    timeline_min_time = -150
    timeline_min_label = "-2:30"

    map_image_html = (
        f"<img src=\"data:image/jpeg;base64,{map_base64}\" class=\"map-image\">"
        if map_base64
        else "<div class=\"placeholder\">地图加载失败</div>"
    )

    points_section_radiant = (
        f"<div class=\"map-body\" id=\"radiantMapBody\">{map_image_html}</div>"
    )
    heatmap_section_radiant_obs = (
        f"<img src=\"data:image/png;base64,{heatmap_base64_radiant_obs}\" class=\"map-image\">"
        if heatmap_base64_radiant_obs
        else (
            f"<img src=\"data:image/jpeg;base64,{map_base64}\" class=\"map-image\">"
            "<div class=\"placeholder\">假眼热力图生成失败</div>"
        )
    )
    heatmap_section_radiant_sen = (
        f"<img src=\"data:image/png;base64,{heatmap_base64_radiant_sen}\" class=\"map-image\">"
        if heatmap_base64_radiant_sen
        else (
            f"<img src=\"data:image/jpeg;base64,{map_base64}\" class=\"map-image\">"
            "<div class=\"placeholder\">真眼热力图生成失败</div>"
        )
    )
    points_section_dire = (
        f"<div class=\"map-body\" id=\"direMapBody\">{map_image_html}</div>"
    )
    heatmap_section_dire_obs = (
        f"<img src=\"data:image/png;base64,{heatmap_base64_dire_obs}\" class=\"map-image\">"
        if heatmap_base64_dire_obs
        else (
            f"<img src=\"data:image/jpeg;base64,{map_base64}\" class=\"map-image\">"
            "<div class=\"placeholder\">假眼热力图生成失败</div>"
        )
    )
    heatmap_section_dire_sen = (
        f"<img src=\"data:image/png;base64,{heatmap_base64_dire_sen}\" class=\"map-image\">"
        if heatmap_base64_dire_sen
        else (
            f"<img src=\"data:image/jpeg;base64,{map_base64}\" class=\"map-image\">"
            "<div class=\"placeholder\">真眼热力图生成失败</div>"
        )
    )

    points_controls_radiant = f"""
        <div class="time-controls" id="radiantControls">
            <div class="time-display" id="radiantTimeDisplay">00:00</div>
            <div class="slider-row">
                <span class="time-label">{timeline_min_label}</span>
                <input type="range" class="time-slider" id="radiantTimeSlider" min="{timeline_min_time}" max="{max_match_duration}" value="{timeline_min_time}">
                <span class="time-label" id="radiantMaxLabel"></span>
            </div>
            <div class="ward-stats">
                <div>当前假眼 <span class="stat-value" id="radiantObsCount">0</span></div>
                <div>当前真眼 <span class="stat-value" id="radiantSenCount">0</span></div>
                <div>总眼位 <span class="stat-value" id="radiantTotalCount">{total_points_radiant}</span></div>
            </div>
            <details class="filter-details">
                <summary>按选手筛选</summary>
                <div class="filter-actions">
                    <button class="filter-button" data-action="select-all-players">全选</button>
                    <button class="filter-button" data-action="clear-all-players">清空</button>
                </div>
                <div class="filter-list">
                    {player_filter_html}
                </div>
            </details>
        </div>
    """
    points_controls_dire = f"""
        <div class="time-controls" id="direControls">
            <div class="time-display" id="direTimeDisplay">00:00</div>
            <div class="slider-row">
                <span class="time-label">{timeline_min_label}</span>
                <input type="range" class="time-slider" id="direTimeSlider" min="{timeline_min_time}" max="{max_match_duration}" value="{timeline_min_time}">
                <span class="time-label" id="direMaxLabel"></span>
            </div>
            <div class="ward-stats">
                <div>当前假眼 <span class="stat-value" id="direObsCount">0</span></div>
                <div>当前真眼 <span class="stat-value" id="direSenCount">0</span></div>
                <div>总眼位 <span class="stat-value" id="direTotalCount">{total_points_dire}</span></div>
            </div>
            <details class="filter-details">
                <summary>按选手筛选</summary>
                <div class="filter-actions">
                    <button class="filter-button" data-action="select-all-players">全选</button>
                    <button class="filter-button" data-action="clear-all-players">清空</button>
                </div>
                <div class="filter-list">
                    {player_filter_html}
                </div>
            </details>
        </div>
    """

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html_mod.escape(source_display)} 的最近比赛的视野分析</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: Arial, sans-serif; background: #0f0f0f; color: #f0f0f0; }}
        .container {{ max-width: 980px; margin: 0 auto; padding: 20px 16px 32px; }}
        h1 {{ text-align: center; margin-bottom: 10px; }}
        .summary {{ text-align: center; color: #aaa; margin-bottom: 14px; }}
        .side-title {{ margin: 18px 0 8px; font-size: 16px; color: #f6f6f6; text-align: center; }}
        .map-container {{ width: 100%; max-width: 800px; margin: 0 auto 16px; border: 2px solid #333; border-radius: 10px; overflow: hidden; background: #111; position: relative; }}
        .map-title {{ padding: 8px 10px; font-size: 13px; color: #f0f0f0; background: rgba(0,0,0,0.5); border-bottom: 1px solid rgba(255,255,255,0.08); }}
        .map-image {{ width: 100%; display: block; }}
        .map-body {{ position: relative; width: 100%; }}
        .ward-dot {{ position: absolute; transform: translate(-50%, -50%); z-index: 5; }}
        .ward-dot img {{ width: 26px; height: 26px; }}
        .ward-dot.hidden {{ opacity: 0; pointer-events: none; }}
        .time-controls {{ width: 100%; max-width: 800px; margin: 6px auto 18px; background: rgba(255,255,255,0.08); padding: 8px 10px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.12); }}
        .time-display {{ text-align: center; font-size: 16px; color: #ffd700; margin-bottom: 6px; }}
        .slider-row {{ display: flex; align-items: center; gap: 8px; }}
        .time-label {{ font-size: 11px; color: #aaa; min-width: 42px; text-align: center; }}
        .time-slider {{ flex: 1; -webkit-appearance: none; height: 6px; border-radius: 6px; background: linear-gradient(to right, #2d5a27 0%, #8b4513 50%, #4a1a1a 100%); outline: none; cursor: pointer; }}
        .time-slider::-webkit-slider-thumb {{ -webkit-appearance: none; width: 14px; height: 14px; border-radius: 50%; background: #ffd700; cursor: pointer; box-shadow: 0 2px 6px rgba(0,0,0,0.4); }}
        .ward-stats {{ display: flex; justify-content: center; gap: 22px; margin-top: 6px; font-size: 12px; color: #ddd; }}
        .ward-stats .stat-value {{ color: #ffd700; font-weight: 600; margin-left: 4px; }}
        .placeholder {{ position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #ccc; }}
        .filter-details {{ margin-top: 8px; border: 1px solid rgba(255,255,255,0.12); border-radius: 8px; padding: 6px 8px; background: rgba(255,255,255,0.06); }}
        .filter-details summary {{ cursor: pointer; font-size: 12px; color: #ddd; }}
        .filter-details[open] summary {{ color: #ffd700; }}
        .filter-actions {{ display: flex; gap: 6px; margin-top: 6px; }}
        .filter-button {{ background: rgba(255,255,255,0.12); color: #f0f0f0; border: 1px solid rgba(255,255,255,0.2); padding: 2px 8px; border-radius: 999px; font-size: 11px; cursor: pointer; }}
        .filter-button:hover {{ background: rgba(255,255,255,0.18); }}
        .filter-list {{ display: flex; flex-wrap: wrap; gap: 6px 10px; margin-top: 6px; max-height: 90px; overflow-y: auto; }}
        .filter-item {{ font-size: 11px; color: #ddd; display: flex; align-items: center; gap: 4px; }}
        .filter-item input {{ accent-color: #ffd700; }}
        .report {{ margin: 12px auto 0; background: rgba(255,255,255,0.06); padding: 12px 14px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); }}
        .report-hidden {{ display: none; }}
        .report h2 {{ font-size: 16px; margin-bottom: 8px; color: #f6f6f6; }}
        .report p, .report li {{ color: #e0e0e0; line-height: 1.6; }}
        .report ul, .report ol {{ margin: 6px 0 12px; padding-left: 16px; list-style-position: inside; }}
        .report li {{ margin: 4px 0; }}
        .report .report-section {{ margin-bottom: 12px; }}
        .report .report-section:last-child {{ margin-bottom: 0; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }}
        th, td {{ padding: 8px 6px; border-bottom: 1px solid rgba(255,255,255,0.1); text-align: left; }}
        th {{ color: #ffd700; }}
        .tag {{ display: inline-block; padding: 2px 8px; border-radius: 999px; background: rgba(255,255,255,0.12); font-size: 12px; color: #ffd700; margin-left: 6px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{html_mod.escape(source_display)} 的最近比赛的视野分析</h1>
        <div class="summary">
            来源: {html_mod.escape(source_display)} |
            比赛数: {len(match_summaries)} |
            假眼: {total_obs} |
            真眼: {total_sen} |
            击杀: {total_kills} |
            推塔: {total_towers}
        </div>
        <div class="summary">
            天辉：假眼 {total_obs_radiant} / 真眼 {total_sen_radiant} |
            夜魇：假眼 {total_obs_dire} / 真眼 {total_sen_dire}
        </div>
        <div class="side-title">天辉 (Radiant) 视野汇总</div>
        <div class="map-container">
            <div class="map-title">眼位点位图</div>
            {points_section_radiant}
        </div>
        {points_controls_radiant}
        <div class="map-container">
            <div class="map-title">假眼热力图</div>
            {heatmap_section_radiant_obs}
        </div>
        <div class="map-container">
            <div class="map-title">真眼热力图</div>
            {heatmap_section_radiant_sen}
        </div>
        <div class="side-title">夜魇 (Dire) 视野汇总</div>
        <div class="map-container">
            <div class="map-title">眼位点位图</div>
            {points_section_dire}
        </div>
        {points_controls_dire}
        <div class="map-container">
            <div class="map-title">假眼热力图</div>
            {heatmap_section_dire_obs}
        </div>
        <div class="map-container">
            <div class="map-title">真眼热力图</div>
            {heatmap_section_dire_sen}
        </div>
        <!--MULTI_MATCH_REPORT-->
        <h2 style="margin-top: 10px; font-size: 16px;">区域假眼存活时长<span class="tag">汇总</span></h2>
        <table>
            <thead>
                <tr>
                    <th>区域</th>
                    <th>样本数</th>
                    <th>平均</th>
                    <th>中位</th>
                    <th>最短</th>
                    <th>最长</th>
                    <th>2分钟内被反率</th>
                    <th>满时存活率</th>
                    <th>时间存活率</th>
                </tr>
            </thead>
            <tbody>
                {ward_lifetime_obs_rows_html}
            </tbody>
        </table>
        <h2 style="margin-top: 10px; font-size: 16px;">区域真眼存活时长<span class="tag">汇总</span></h2>
        <table>
            <thead>
                <tr>
                    <th>区域</th>
                    <th>样本数</th>
                    <th>平均</th>
                    <th>中位</th>
                    <th>最短</th>
                    <th>最长</th>
                    <th>2分钟内被反率</th>
                    <th>满时存活率</th>
                    <th>时间存活率</th>
                </tr>
            </thead>
            <tbody>
                {ward_lifetime_sen_rows_html}
            </tbody>
        </table>
        <h2 style="margin-top: 10px; font-size: 16px;">区域统计<span class="tag">汇总</span></h2>
        {region_note}
        <div class="side-title">天辉区域分布</div>
        <table>
            <thead>
                <tr>
                    <th>区域</th>
                    <th>假眼</th>
                    <th>真眼</th>
                    <th>合计</th>
                    <th>占比</th>
                </tr>
            </thead>
            <tbody>
                {region_rows_radiant_html}
            </tbody>
        </table>
        <div class="side-title" style="margin-top: 12px;">夜魇区域分布</div>
        <table>
            <thead>
                <tr>
                    <th>区域</th>
                    <th>假眼</th>
                    <th>真眼</th>
                    <th>合计</th>
                    <th>占比</th>
                </tr>
            </thead>
            <tbody>
                {region_rows_dire_html}
            </tbody>
        </table>
        <h2 style="margin-top: 10px; font-size: 16px;">比赛列表<span class="tag">汇总</span></h2>
        <table>
            <thead>
                <tr>
                    <th>Match ID</th>
                    <th>对阵</th>
                    <th>阵营</th>
                    <th>天辉假/真</th>
                    <th>夜魇假/真</th>
                    <th>击杀</th>
                    <th>推塔</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        <h2 style="margin-top: 10px; font-size: 16px;">团战视野分析<span class="tag">Teamfight</span></h2>
        <table>
            <thead>
                <tr>
                    <th>Match</th>
                    <th>时间</th>
                    <th>区域</th>
                    <th>进攻视野</th>
                    <th>敌方死亡</th>
                    <th>己方死亡</th>
                    <th>击杀差</th>
                    <th>团战结果</th>
                </tr>
            </thead>
            <tbody>
                {teamfight_rows_html}
            </tbody>
        </table>
        <h2 style="margin-top: 10px; font-size: 16px;">团战击杀效率 × 进攻视野<span class="tag">汇总</span></h2>
        <table>
            <thead>
                <tr>
                    <th>进攻视野</th>
                    <th>团战数</th>
                    <th>平均敌方死亡</th>
                    <th>平均己方死亡</th>
                    <th>平均击杀差</th>
                    <th>胜率</th>
                </tr>
            </thead>
            <tbody>
                {teamfight_summary_rows_html}
            </tbody>
        </table>
    </div>
    <script>
        const wardIcons = {{
            "obs_radiant": "data:image/png;base64,{icon_base64.get('obs_radiant', '')}",
            "obs_dire": "data:image/png;base64,{icon_base64.get('obs_dire', '')}",
            "sen_radiant": "data:image/png;base64,{icon_base64.get('sen_radiant', '')}",
            "sen_dire": "data:image/png;base64,{icon_base64.get('sen_dire', '')}"
        }};
        const radiantWards = {json.dumps(wards_radiant_data, ensure_ascii=False)};
        const direWards = {json.dumps(wards_dire_data, ensure_ascii=False)};
        const playerFilterInputs = document.querySelectorAll('input[name="playerFilter"]');
        const selectAllButtons = document.querySelectorAll('[data-action="select-all-players"]');
        const clearAllButtons = document.querySelectorAll('[data-action="clear-all-players"]');
        const updateHandlers = [];

        function formatTime(seconds) {{
            const sign = seconds < 0 ? '-' : '';
            const absSeconds = Math.abs(seconds);
            const mins = Math.floor(absSeconds / 60);
            const secs = absSeconds % 60;
            return sign + mins + ':' + secs.toString().padStart(2, '0');
        }}

        function getSelectedPlayers() {{
            const selected = new Set();
            playerFilterInputs.forEach((input) => {{
                if (input.checked) {{
                    selected.add(input.value);
                }}
            }});
            return Array.from(selected);
        }}

        function syncPlayerCheckboxes(value, checked) {{
            playerFilterInputs.forEach((input) => {{
                if (input.value === value) {{
                    input.checked = checked;
                }}
            }});
        }}

        function updateAllMaps() {{
            updateHandlers.forEach((handler) => handler());
        }}

        function initWardMap(options) {{
            const mapBody = document.getElementById(options.mapBodyId);
            const slider = document.getElementById(options.sliderId);
            const display = document.getElementById(options.displayId);
            const obsCount = document.getElementById(options.obsCountId);
            const senCount = document.getElementById(options.senCountId);
            const maxLabel = document.getElementById(options.maxLabelId);
            const totalCount = document.getElementById(options.totalCountId);
            const wards = options.wards || [];

            if (!mapBody || !slider) {{
                return;
            }}

            const wardElements = [];
            wards.forEach((ward) => {{
                const xPercent = (ward.x / 128) * 100;
                const yPercent = (1 - ward.y / 128) * 100;
                const div = document.createElement('div');
                div.className = 'ward-dot hidden';
                div.style.left = xPercent + '%';
                div.style.top = yPercent + '%';
                const img = document.createElement('img');
                img.src = wardIcons[ward.type] || '';
                div.appendChild(img);
                mapBody.appendChild(div);
                wardElements.push(div);
            }});

            if (totalCount) {{
                totalCount.textContent = wards.length;
            }}
            if (maxLabel) {{
                maxLabel.textContent = formatTime(parseInt(slider.max || '0'));
            }}

            const update = (currentTime) => {{
                let obs = 0;
                let sen = 0;
                const minTime = parseInt(slider.min || '0');
                const showAll = currentTime <= minTime;
                const selectedPlayers = getSelectedPlayers();
                const hasPlayerFilter = selectedPlayers.length > 0;
                const playerSet = new Set(selectedPlayers);
                wards.forEach((ward, index) => {{
                    const hasEnd = ward.end_time !== null && ward.end_time !== undefined;
                    const visible = showAll || (ward.time <= currentTime && (!hasEnd || currentTime < ward.end_time));
                    const matchesPlayer = !hasPlayerFilter || playerSet.has(ward.player);
                    if (visible && matchesPlayer) {{
                        wardElements[index].classList.remove('hidden');
                        if (ward.is_obs) {{
                            obs += 1;
                        }} else {{
                            sen += 1;
                        }}
                    }} else {{
                        wardElements[index].classList.add('hidden');
                    }}
                }});
                if (obsCount) {{
                    obsCount.textContent = obs;
                }}
                if (senCount) {{
                    senCount.textContent = sen;
                }}
            }};

            const setDisplay = (value) => {{
                if (display) {{
                    const minTime = parseInt(slider.min || '0');
                    display.textContent = value <= minTime ? '全部' : formatTime(value);
                }}
            }};

            const initValue = parseInt(slider.value || '0');
            setDisplay(initValue);
            update(initValue);
            updateHandlers.push(() => {{
                const value = parseInt(slider.value || '0');
                setDisplay(value);
                update(value);
            }});
            slider.addEventListener('input', () => {{
                const value = parseInt(slider.value || '0');
                setDisplay(value);
                update(value);
            }});
        }}

        initWardMap({{
            mapBodyId: 'radiantMapBody',
            sliderId: 'radiantTimeSlider',
            displayId: 'radiantTimeDisplay',
            obsCountId: 'radiantObsCount',
            senCountId: 'radiantSenCount',
            maxLabelId: 'radiantMaxLabel',
            totalCountId: 'radiantTotalCount',
            wards: radiantWards
        }});
        initWardMap({{
            mapBodyId: 'direMapBody',
            sliderId: 'direTimeSlider',
            displayId: 'direTimeDisplay',
            obsCountId: 'direObsCount',
            senCountId: 'direSenCount',
            maxLabelId: 'direMaxLabel',
            totalCountId: 'direTotalCount',
            wards: direWards
        }});
        if (playerFilterInputs.length) {{
            playerFilterInputs.forEach((input) => {{
                input.addEventListener('change', (event) => {{
                    const target = event.target;
                    if (target && target.value !== undefined) {{
                        syncPlayerCheckboxes(target.value, target.checked);
                    }}
                    updateAllMaps();
                }});
            }});
        }}
        if (selectAllButtons.length) {{
            selectAllButtons.forEach((btn) => {{
                btn.addEventListener('click', () => {{
                    playerFilterInputs.forEach((input) => {{
                        input.checked = true;
                    }});
                    updateAllMaps();
                }});
            }});
        }}
        if (clearAllButtons.length) {{
            clearAllButtons.forEach((btn) => {{
                btn.addEventListener('click', () => {{
                    playerFilterInputs.forEach((input) => {{
                        input.checked = false;
                    }});
                    updateAllMaps();
                }});
            }});
        }}
    </script>
</body>
</html>
"""

    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        logger.info("analyze_multi_match_wards: saved file %s", html_path)
    except Exception as e:
        logger.warning("analyze_multi_match_wards: failed to save file %s: %s", html_path, e)

    debug_log_path = ""
    if debug and debug_lines:
        debug_log_path = os.path.join(
            WARD_OUTPUT_DIR,
            f"ward_mapping_debug_{source_label}_{timestamp}.log",
        )
        with open(debug_log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(debug_lines))

    result_lines = [
        "# 多场比赛视野汇总",
        f"- 来源: {source_display}",
        f"- 比赛数量: {len(match_summaries)}",
        f"- 眼位总计: 假眼 {total_obs} / 真眼 {total_sen}",
        f"- 天辉眼位: 假眼 {total_obs_radiant} / 真眼 {total_sen_radiant}",
        f"- 夜魇眼位: 假眼 {total_obs_dire} / 真眼 {total_sen_dire}",
        f"- 击杀总计: {total_kills}",
        f"- 推塔总计: {total_towers}",
        f"- 交互式网页: {html_path}",
        f"- 汇总数据: {json_path}",
    ]

    def _fmt_duration(value: Optional[float]) -> str:
        if value is None:
            return "-"
        try:
            seconds = int(round(float(value)))
        except (TypeError, ValueError):
            return "-"
        minutes, secs = divmod(max(seconds, 0), 60)
        return f"{minutes}:{secs:02d}"

    obs_avg = _fmt_duration(ward_lifetime["obs"].get("avg"))
    obs_median = _fmt_duration(ward_lifetime["obs"].get("median"))
    sen_avg = _fmt_duration(ward_lifetime["sen"].get("avg"))
    sen_median = _fmt_duration(ward_lifetime["sen"].get("median"))
    result_lines.insert(
        6,
        f"- 眼位存活: 假眼 平均 {obs_avg} / 中位 {obs_median} | 真眼 平均 {sen_avg} / 中位 {sen_median}",
    )
    if debug_log_path:
        result_lines.append(f"- 区域映射调试日志: {debug_log_path}")

    if skipped:
        skipped_lines = ", ".join(str(s.get("match_id")) for s in skipped[:10])
        result_lines.append("- ⚠️ 跳过 %d 场比赛: %s" % (len(skipped), skipped_lines))

    logger.info("analyze_multi_match_wards: completed for %d matches", len(match_summaries))
    return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# 3. inject_multi_match_ward_report_html
# ---------------------------------------------------------------------------


@mcp.tool()
async def inject_multi_match_ward_report_html(
    match_ids: List[int],
    output_path: Optional[str] = None,
) -> str:
    """生成并保存多场比赛视野汇总 HTML 报告

    Args:
        match_ids: 比赛ID列表
        output_path: HTML 输出路径（可选，默认自动生成）

    Returns:
        JSON 字符串：包含汇总数据与写入结果
    """
    logger.info("inject_multi_match_ward_report_html called with: match_ids=%s, output_path=%s", match_ids, output_path)
    try:
        client = OpenDotaClient.get_instance()
        if client is None:
            logger.warning("inject_multi_match_ward_report_html: OpenDota client not initialized")
            return "❌ OpenDota 客户端未初始化"

        # Reuse the main analysis function, forcing HTML generation
        summary = await analyze_multi_match_wards(
            match_ids=match_ids,
            generate_html=True,
        )

        # Find the generated HTML path from the summary text
        html_path_match = re.search(r"交互式网页: (.+)", summary)
        if not html_path_match:
            logger.warning("inject_multi_match_ward_report_html: HTML generation failed, no path found in summary")
            return "❌ HTML 生成失败\n\n%s" % summary

        html_path = html_path_match.group(1).strip()

        if output_path:
            try:
                import shutil
                shutil.copy2(html_path, output_path)
                logger.info("inject_multi_match_ward_report_html: saved file %s", output_path)
                return "✅ 多场比赛视野报告已保存: %s" % output_path
            except Exception as e:
                logger.warning("inject_multi_match_ward_report_html: failed to save file %s: %s", output_path, e)
                return "❌ 保存失败: %s" % e

        logger.info("inject_multi_match_ward_report_html: saved file %s", html_path)
        return "✅ 多场比赛视野报告已保存: %s" % html_path
    except Exception as e:
        logger.error("inject_multi_match_ward_report_html: failed for match_ids=%s: %s", match_ids, e, exc_info=True)
        return "❌ 生成失败: %s" % e


# ---------------------------------------------------------------------------
# 4. inject_ward_report_html
# ---------------------------------------------------------------------------


@mcp.tool()
async def inject_ward_report_html(
    match_id: int,
    output_path: Optional[str] = None,
) -> str:
    """生成并保存单场比赛视野分析 HTML 报告

    Args:
        match_id: Dota 2 比赛ID
        output_path: HTML 输出路径（可选，默认自动生成）

    Returns:
        生成结果与文件路径
    """
    logger.info("inject_ward_report_html called with: match_id=%s, output_path=%s", match_id, output_path)
    try:
        client = OpenDotaClient.get_instance()
        if client is None:
            logger.warning("inject_ward_report_html: OpenDota client not initialized")
            return "❌ OpenDota 客户端未初始化"

        # Reuse the main analysis function, forcing HTML generation
        summary = await analyze_match_wards(
            match_id=match_id,
            generate_html=True,
        )

        # Find the generated HTML path from the summary text
        html_path_match = re.search(r"交互式网页: (.+)", summary)
        if not html_path_match:
            logger.warning("inject_ward_report_html: HTML generation failed for match_id=%s", match_id)
            return "❌ HTML 生成失败\n\n%s" % summary

        html_path = html_path_match.group(1).strip()

        if output_path:
            try:
                import shutil
                shutil.copy2(html_path, output_path)
                logger.info("inject_ward_report_html: saved file %s", output_path)
                return "✅ 视野分析报告已保存: %s" % output_path
            except Exception as e:
                logger.warning("inject_ward_report_html: failed to save file %s: %s", output_path, e)
                return "❌ 保存失败: %s" % e

        logger.info("inject_ward_report_html: saved file %s", html_path)
        return "✅ 视野分析报告已保存: %s" % html_path
    except Exception as e:
        logger.error("inject_ward_report_html: failed for match_id=%s: %s", match_id, e, exc_info=True)
        return "❌ 生成失败: %s" % e


# ---------------------------------------------------------------------------
# 5. get_ward_statistics
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_ward_statistics(match_id: int) -> str:
    """获取指定比赛的眼位统计数据（不生成可视化文件）

    Args:
        match_id: Dota 2 比赛ID

    Returns:
        眼位统计数据，包括假眼、真眼的数量和时间分布
    """
    logger.info("get_ward_statistics called with: match_id=%s", match_id)
    try:
        client = OpenDotaClient.get_instance()
        if client is None:
            logger.warning("get_ward_statistics: OpenDota client not initialized")
            return "❌ OpenDota 客户端未初始化"

        # Fetch match details
        match_data = await client.get("matches/%s" % match_id)

        if isinstance(match_data, dict) and "error" in match_data:
            logger.warning("get_ward_statistics: API returned error for match_id=%s: %s", match_id, match_data.get("error"))
            return "❌ API 错误: %s" % match_data["error"]

        if not match_data:
            logger.warning("get_ward_statistics: no match data for match_id=%s", match_id)
            return "❌ 无法获取比赛 %s 的数据" % match_id

        logger.info("get_ward_statistics: fetched match data for match_id=%s", match_id)

        # Extract ward data
        extractor = WardDataExtractor()

        if not extractor.extract_from_match(match_data):
            logger.warning("get_ward_statistics: no ward data extracted for match_id=%s", match_id)
            return "❌ 比赛 %s 无眼位数据（可能未解析或无观察者数据）" % match_id

        df_obs, df_sen = extractor.get_dataframes()

        if df_obs.empty and df_sen.empty:
            logger.warning("get_ward_statistics: empty dataframes for match_id=%s", match_id)
            return "❌ 比赛 %s 无眼位数据" % match_id

        logger.info("get_ward_statistics: extracted %d observer wards, %d sentry wards", len(df_obs), len(df_sen))

        # Team names
        radiant_name: str = match_data.get("radiant_name") or "天辉 Radiant"
        dire_name: str = match_data.get("dire_name") or "夜魇 Dire"

        # Create analyzer
        analyzer = WardAnalyzer(df_obs, df_sen, radiant_name, dire_name)

        # Return stats summary
        logger.info("get_ward_statistics: completed for match_id=%s", match_id)
        return analyzer.get_stats_summary()
    except Exception as e:
        logger.error("get_ward_statistics: failed for match_id=%s: %s", match_id, e, exc_info=True)
        return "❌ 统计失败: %s" % e
