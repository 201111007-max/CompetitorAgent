"""Ward visualization and analysis module.

Extracted from dota2_fastmcp.py (lines 1144-2479). Contains:

- ``build_ward_report_data``: structured ward report builder
- ``build_multi_match_region_summary``: multi-match region aggregation
- ``WardDataExtractor``: extract ward data from match JSON
- ``WardAnalyzer``: scatter plots, interactive HTML, heatmap generation

All private ``_function`` names from the monolith have been made public.
Heavy dependencies (matplotlib, PIL, cv2) are lazily imported with
``HAS_MATPLOTLIB``, ``HAS_PIL``, ``HAS_OPENCV`` guards.
"""

import base64
import html
import json
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .hero_names import get_cn_name
from .map_config import (
    MAPS_DIR,
    MAP_VERSION,
    RESOURCES_DIR,
    format_time_mmss,
    gaussian_blur,
    get_map_path,
    load_region_template,
    match_region,
    parse_tower_key,
)
from .opendota import OpenDotaClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy heavy dependency imports
# ---------------------------------------------------------------------------

try:
    import matplotlib  # noqa: F401
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: F401
    import matplotlib.patches as mpatches  # noqa: F401
    from matplotlib.offsetbox import AnnotationBbox, OffsetImage  # noqa: F401

    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    from PIL import Image  # noqa: F401

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import cv2  # noqa: F401

    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

# ---------------------------------------------------------------------------
# Directory constants (derived from RESOURCES_DIR)
# ---------------------------------------------------------------------------

FIGURE_DIR: str = str(RESOURCES_DIR / "figure")

# Region template path (for report metadata)
REGION_TEMPLATE_PATH: str = str(RESOURCES_DIR / f"ward_region_template_{MAP_VERSION}.json")


# ---------------------------------------------------------------------------
# Helper: build hero map via OpenDotaClient cached data
# ---------------------------------------------------------------------------


def build_hero_map() -> Dict[int, str]:
    """Build a hero_id -> en_name mapping using the OpenDotaClient cached data.

    Falls back to an empty dict if the client is not initialised or has
    no cached heroes.

    Returns:
        Dict[int, str]: hero_id to English localized name.
    """
    client = OpenDotaClient.get_instance()
    if client is None:
        logger.warning("OpenDotaClient not initialised; hero map will be empty")
        return {}
    heroes = client._heroes_cache
    if heroes is None:
        logger.warning("OpenDotaClient heroes cache is empty; hero map will be empty")
        return {}
    return {h["id"]: h.get("localized_name", f"Hero {h['id']}") for h in heroes if "id" in h}


# ---------------------------------------------------------------------------
# Helper: item map / item entry via OpenDotaClient
# ---------------------------------------------------------------------------


def load_items_map() -> Dict[int, Dict[str, str]]:
    """Load item constants map using the OpenDotaClient cached data.

    Returns:
        Dict[int, Dict[str, str]]: item_id -> {key, name, qual}
    """
    client = OpenDotaClient.get_instance()
    if client is None:
        logger.warning("OpenDotaClient not initialised; items map will be empty")
        return {}
    items_cache = client._items_cache
    if items_cache is None:
        return {}
    # Transform to the expected {id: {key, name, qual}} format
    result: Dict[int, Dict[str, str]] = {}
    for item_id, info in items_cache.items():
        key = info.get("name", "")
        name = info.get("dname") or info.get("name") or key
        result[item_id] = {
            "key": str(key),
            "name": str(name),
            "qual": info.get("qual"),
        }
    return result


def build_item_entry(
    item_id: Any,
    item_map: Dict[int, Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    """Build a single item info dict; returns None for empty/invalid items.

    Args:
        item_id: The item ID (may be any type; int-castable).
        item_map: The items map from :func:`load_items_map`.

    Returns:
        Optional[Dict[str, Any]]: {id, key, name} or None.
    """
    if item_id is None:
        return None
    try:
        item_id_int = int(item_id)
    except (TypeError, ValueError):
        return None
    if item_id_int <= 0:
        return None
    info = item_map.get(item_id_int)
    if info:
        return {"id": item_id_int, "key": info.get("key"), "name": info.get("name")}
    return {"id": item_id_int, "key": None, "name": None}


# ---------------------------------------------------------------------------
# build_ward_report_data
# ---------------------------------------------------------------------------


def build_ward_report_data(
    df_obs: pd.DataFrame,
    df_sen: pd.DataFrame,
    radiant_name: str,
    dire_name: str,
    match_duration: Optional[int],
    radiant_players: List[Dict[str, Any]],
    dire_players: List[Dict[str, Any]],
    objectives: Optional[List[Dict[str, Any]]] = None,
    tower_status: Optional[Dict[str, Optional[int]]] = None,
    kill_events: Optional[List[Dict[str, Any]]] = None,
    bucket_seconds: int = 300,
) -> Dict[str, Any]:
    """Build structured data for the vision analysis report.

    Args:
        df_obs: Observer ward DataFrame.
        df_sen: Sentry ward DataFrame.
        radiant_name: Radiant team name.
        dire_name: Dire team name.
        match_duration: Match duration in seconds.
        radiant_players: Radiant player info list.
        dire_players: Dire player info list.
        objectives: Optional objectives event list.
        tower_status: Optional tower status masks.
        kill_events: Optional kill event list.
        bucket_seconds: Time bucket size in seconds.

    Returns:
        Dict[str, Any]: Structured ward report data.
    """
    # Player mapping (hero_id -> player info)
    player_by_hero_id: Dict[int, Dict[str, str]] = {}
    for p in radiant_players:
        hero_id = int(p.get("hero_id", 0))
        player_by_hero_id[hero_id] = {
            "team": "radiant",
            "team_name": radiant_name,
            "player": str(p.get("player", "Unknown")),
            "hero": str(p.get("hero", "Unknown")),
        }
    for p in dire_players:
        hero_id = int(p.get("hero_id", 0))
        player_by_hero_id[hero_id] = {
            "team": "dire",
            "team_name": dire_name,
            "player": str(p.get("player", "Unknown")),
            "hero": str(p.get("hero", "Unknown")),
        }

    # Player ward contribution stats
    player_stats_map: Dict[str, Dict[str, Any]] = {}

    def ensure_player_stat(hero_id: int, is_radiant: int) -> Dict[str, Any]:
        info = player_by_hero_id.get(hero_id)
        team_name = radiant_name if is_radiant == 1 else dire_name
        player_name = info.get("player") if info else "Unknown"
        hero_name = info.get("hero") if info else f"Hero {hero_id}"
        key = f"{team_name}:{hero_id}:{player_name}"
        if key not in player_stats_map:
            player_stats_map[key] = {
                "team": team_name,
                "player": player_name,
                "hero": hero_name,
                "obs": 0,
                "sen": 0,
                "total": 0,
                "first_time": None,
                "last_time": None,
            }
        return player_stats_map[key]

    if not df_obs.empty:
        for _, row in df_obs.iterrows():
            hero_id = int(row.get("hero_id", 0))
            is_radiant = int(row.get("is_radiant", 0))
            stat = ensure_player_stat(hero_id, is_radiant)
            stat["obs"] += 1
            stat["total"] += 1
            t = int(row.get("time", 0))
            stat["first_time"] = t if stat["first_time"] is None else min(stat["first_time"], t)
            stat["last_time"] = t if stat["last_time"] is None else max(stat["last_time"], t)

    if not df_sen.empty:
        for _, row in df_sen.iterrows():
            hero_id = int(row.get("hero_id", 0))
            is_radiant = int(row.get("is_radiant", 0))
            stat = ensure_player_stat(hero_id, is_radiant)
            stat["sen"] += 1
            stat["total"] += 1
            t = int(row.get("time", 0))
            stat["first_time"] = t if stat["first_time"] is None else min(stat["first_time"], t)
            stat["last_time"] = t if stat["last_time"] is None else max(stat["last_time"], t)

    player_stats = list(player_stats_map.values())
    for stat in player_stats:
        if stat["first_time"] is not None:
            stat["first_time"] = format_time_mmss(stat["first_time"])
        if stat["last_time"] is not None:
            stat["last_time"] = format_time_mmss(stat["last_time"])

    # Map region statistics
    regions = load_region_template()
    region_stats_map: Dict[str, Dict[str, Any]] = {}
    ward_regions: List[Dict[str, Any]] = []

    def ensure_region_stat(label: str, key: Optional[str]) -> Dict[str, Any]:
        if label not in region_stats_map:
            region_stats_map[label] = {
                "key": key,
                "label": label,
                "obs_radiant": 0,
                "obs_dire": 0,
                "sen_radiant": 0,
                "sen_dire": 0,
                "total": 0,
            }
        return region_stats_map[label]

    def collect_region_for_row(row: pd.Series, is_obs: bool) -> None:
        x = row.get("x")
        y = row.get("y")
        if x is None or y is None:
            return
        try:
            x_val = float(x)
            y_val = float(y)
        except (TypeError, ValueError):
            return

        primary_key, primary_label, labels = match_region(x_val, y_val, regions)
        label = primary_label or "未知区域"
        key = primary_key

        is_radiant = int(row.get("is_radiant", 0)) == 1
        stat = ensure_region_stat(label, key)
        if is_obs:
            if is_radiant:
                stat["obs_radiant"] += 1
            else:
                stat["obs_dire"] += 1
        else:
            if is_radiant:
                stat["sen_radiant"] += 1
            else:
                stat["sen_dire"] += 1
        stat["total"] += 1

        ward_regions.append({
            "x": x_val,
            "y": y_val,
            "time": int(row.get("time", 0)),
            "is_obs": is_obs,
            "team": "radiant" if is_radiant else "dire",
            "region": label,
            "region_key": key,
            "region_labels": labels,
        })

    if not df_obs.empty:
        for _, row in df_obs.iterrows():
            collect_region_for_row(row, is_obs=True)
    if not df_sen.empty:
        for _, row in df_sen.iterrows():
            collect_region_for_row(row, is_obs=False)

    region_summary = sorted(
        region_stats_map.values(), key=lambda x: x.get("total", 0), reverse=True
    )

    # Tower events and kill events
    tower_events: List[Dict[str, Any]] = []
    tower_summary: Dict[str, int] = {"radiant": 0, "dire": 0}
    for obj in objectives or []:
        if obj.get("type") != "building_kill":
            continue
        key = str(obj.get("key", ""))
        if "tower" not in key:
            continue
        info = parse_tower_key(key)
        tower_team = info.get("team")
        if tower_team in tower_summary:
            tower_summary[tower_team] += 1
        tower_events.append({
            "time": int(obj.get("time", 0)),
            "key": key,
            "tower_team": tower_team,
            "lane": info.get("lane"),
            "tier": info.get("tier"),
            "unit": obj.get("unit"),
            "player_slot": obj.get("player_slot"),
            "slot": obj.get("slot"),
        })
    tower_events.sort(key=lambda x: x.get("time", 0))

    kill_events_list = list(kill_events or [])
    kill_events_list.sort(key=lambda x: x.get("time", 0))

    # Time bucket statistics
    times: List[float] = []
    if not df_obs.empty:
        times.extend(df_obs["time"].dropna().tolist())
    if not df_sen.empty:
        times.extend(df_sen["time"].dropna().tolist())

    time_buckets: List[Dict[str, Any]] = []
    if times:
        min_time = int(min(times))
        max_time = int(max(times))
        start_time = min_time if min_time < 0 else 0
        if match_duration and match_duration > 0:
            max_time = max(max_time, int(match_duration))

        bucket_start = int(np.floor(start_time / bucket_seconds)) * bucket_seconds
        bucket_end = int(np.floor(max_time / bucket_seconds)) * bucket_seconds

        for t in range(bucket_start, bucket_end + bucket_seconds, bucket_seconds):
            t_end = t + bucket_seconds
            obs_bucket = (
                df_obs[(df_obs["time"] >= t) & (df_obs["time"] < t_end)]
                if not df_obs.empty
                else pd.DataFrame()
            )
            sen_bucket = (
                df_sen[(df_sen["time"] >= t) & (df_sen["time"] < t_end)]
                if not df_sen.empty
                else pd.DataFrame()
            )

            rad_obs = len(obs_bucket[obs_bucket["is_radiant"] == 1]) if not obs_bucket.empty else 0
            dir_obs = len(obs_bucket[obs_bucket["is_radiant"] == 0]) if not obs_bucket.empty else 0
            rad_sen = len(sen_bucket[sen_bucket["is_radiant"] == 1]) if not sen_bucket.empty else 0
            dir_sen = len(sen_bucket[sen_bucket["is_radiant"] == 0]) if not sen_bucket.empty else 0
            total = rad_obs + dir_obs + rad_sen + dir_sen

            time_buckets.append({
                "start": t,
                "end": t_end,
                "label": f"{format_time_mmss(t)}-{format_time_mmss(t_end)}",
                "radiant_obs": rad_obs,
                "dire_obs": dir_obs,
                "radiant_sen": rad_sen,
                "dire_sen": dir_sen,
                "total": total,
            })

    # Team totals
    obs_rad = len(df_obs[df_obs["is_radiant"] == 1]) if not df_obs.empty else 0
    obs_dir = len(df_obs[df_obs["is_radiant"] == 0]) if not df_obs.empty else 0
    sen_rad = len(df_sen[df_sen["is_radiant"] == 1]) if not df_sen.empty else 0
    sen_dir = len(df_sen[df_sen["is_radiant"] == 0]) if not df_sen.empty else 0

    def team_first_time(df: pd.DataFrame, is_radiant: int) -> Optional[str]:
        if df.empty:
            return None
        subset = df[df["is_radiant"] == is_radiant]
        if subset.empty:
            return None
        return format_time_mmss(int(subset["time"].min()))

    first_time_radiant = team_first_time(
        pd.concat([df_obs, df_sen], ignore_index=True), 1
    )
    first_time_dire = team_first_time(
        pd.concat([df_obs, df_sen], ignore_index=True), 0
    )

    top_windows = sorted(
        time_buckets, key=lambda x: x.get("total", 0), reverse=True
    )[:3]

    match_id: Optional[int] = None
    if not df_obs.empty and "match_id" in df_obs.columns:
        match_id = int(df_obs["match_id"].iloc[0])
    elif not df_sen.empty and "match_id" in df_sen.columns:
        match_id = int(df_sen["match_id"].iloc[0])

    return {
        "match_id": match_id,
        "duration": int(match_duration) if match_duration else None,
        "bucket_seconds": bucket_seconds,
        "radiant_name": radiant_name,
        "dire_name": dire_name,
        "ward_totals": {
            "radiant": {"obs": obs_rad, "sen": sen_rad, "total": obs_rad + sen_rad},
            "dire": {"obs": obs_dir, "sen": sen_dir, "total": obs_dir + sen_dir},
        },
        "first_ward_time": {
            "radiant": first_time_radiant,
            "dire": first_time_dire,
        },
        "region_template": REGION_TEMPLATE_PATH if regions else None,
        "region_summary": region_summary,
        "ward_regions": ward_regions,
        "tower_status": tower_status or {"radiant": None, "dire": None},
        "tower_summary": tower_summary,
        "tower_events": tower_events,
        "kill_events": kill_events_list,
        "time_buckets": time_buckets,
        "top_windows": top_windows,
        "player_stats": sorted(
            player_stats, key=lambda x: x.get("total", 0), reverse=True
        ),
    }


# ---------------------------------------------------------------------------
# build_multi_match_region_summary
# ---------------------------------------------------------------------------


def build_multi_match_region_summary(
    obs_rows: List[Dict[str, Any]],
    sen_rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Aggregate region statistics across multiple matches.

    Args:
        obs_rows: Observer ward row dicts (with x, y, is_radiant).
        sen_rows: Sentry ward row dicts (with x, y, is_radiant).

    Returns:
        Tuple of (region_summary_list, region_template_path_or_None).
    """
    regions = load_region_template()
    region_stats_map: Dict[str, Dict[str, Any]] = {}

    def ensure_region_stat(label: str, key: Optional[str]) -> Dict[str, Any]:
        if label not in region_stats_map:
            region_stats_map[label] = {
                "key": key,
                "label": label,
                "obs_radiant": 0,
                "obs_dire": 0,
                "sen_radiant": 0,
                "sen_dire": 0,
                "total": 0,
            }
        return region_stats_map[label]

    def collect_row(row: Dict[str, Any], is_obs: bool) -> None:
        x = row.get("x")
        y = row.get("y")
        if x is None or y is None:
            return
        try:
            x_val = float(x)
            y_val = float(y)
        except (TypeError, ValueError):
            return

        primary_key, primary_label, _labels = match_region(x_val, y_val, regions)
        label = primary_label or "未知区域"
        key = primary_key
        is_radiant = int(row.get("is_radiant", 0)) == 1

        stat = ensure_region_stat(label, key)
        if is_obs:
            if is_radiant:
                stat["obs_radiant"] += 1
            else:
                stat["obs_dire"] += 1
        else:
            if is_radiant:
                stat["sen_radiant"] += 1
            else:
                stat["sen_dire"] += 1
        stat["total"] += 1

    for row in obs_rows:
        collect_row(row, is_obs=True)
    for row in sen_rows:
        collect_row(row, is_obs=False)

    region_summary = sorted(
        region_stats_map.values(), key=lambda x: x.get("total", 0), reverse=True
    )
    template_path = REGION_TEMPLATE_PATH if regions else None
    return region_summary, template_path


# ---------------------------------------------------------------------------
# WardDataExtractor
# ---------------------------------------------------------------------------


class WardDataExtractor:
    """Extract ward information from match data."""

    def __init__(self) -> None:
        self.obs_data: List[Dict[str, Any]] = []
        self.sen_data: List[Dict[str, Any]] = []

    def extract_from_match(self, match_data: Dict[str, Any]) -> bool:
        """Extract ward data from a single match.

        Args:
            match_data: Match JSON data dict.

        Returns:
            bool: True if any wards were extracted.
        """
        if not match_data:
            return False

        match_id = match_data.get("match_id")
        start_time = match_data.get("start_time", 0)
        patch = match_data.get("patch", 0)

        # Map version
        map_version = MAP_VERSION

        # Check for parsed data
        if not match_data.get("players"):
            return False

        # Extract objective event times
        objectives = match_data.get("objectives", [])
        obj_times = self.extract_objectives(match_id, objectives)

        # Extract wards from each player
        for player in match_data.get("players", []):
            hero_id = player.get("hero_id")
            player_slot = player.get("player_slot", 0)
            is_radiant = 1 if player_slot < 128 else 0

            obs_left_map: Dict[int, int] = {}
            for left_entry in player.get("obs_left_log", []) or []:
                ehandle = left_entry.get("ehandle")
                if ehandle is None:
                    continue
                left_time = int(left_entry.get("time", 0))
                prev_time = obs_left_map.get(ehandle)
                if prev_time is None or left_time < prev_time:
                    obs_left_map[ehandle] = left_time

            sen_left_map: Dict[int, int] = {}
            for left_entry in player.get("sen_left_log", []) or []:
                ehandle = left_entry.get("ehandle")
                if ehandle is None:
                    continue
                left_time = int(left_entry.get("time", 0))
                prev_time = sen_left_map.get(ehandle)
                if prev_time is None or left_time < prev_time:
                    sen_left_map[ehandle] = left_time

            # Extract observer wards
            obs_log = player.get("obs_log", [])
            for ward in obs_log:
                ehandle = ward.get("ehandle")
                left_time = obs_left_map.get(ehandle) if ehandle is not None else None
                self.obs_data.append({
                    "match_id": match_id,
                    "start_time": start_time,
                    "patch": patch,
                    "map_version": map_version,
                    "hero_id": hero_id,
                    "is_radiant": is_radiant,
                    "time": ward.get("time", 0),
                    "x": ward.get("x", 0),
                    "y": ward.get("y", 0),
                    "z": ward.get("z", 0),
                    "ehandle": ehandle,
                    "left_time": left_time,
                    **obj_times,
                })

            # Extract sentry wards
            sen_log = player.get("sen_log", [])
            for ward in sen_log:
                ehandle = ward.get("ehandle")
                left_time = sen_left_map.get(ehandle) if ehandle is not None else None
                self.sen_data.append({
                    "match_id": match_id,
                    "start_time": start_time,
                    "patch": patch,
                    "map_version": map_version,
                    "hero_id": hero_id,
                    "is_radiant": is_radiant,
                    "time": ward.get("time", 0),
                    "x": ward.get("x", 0),
                    "y": ward.get("y", 0),
                    "z": ward.get("z", 0),
                    "ehandle": ehandle,
                    "left_time": left_time,
                    **obj_times,
                })

        obs_count = len([w for w in self.obs_data if w["match_id"] == match_id])
        sen_count = len([w for w in self.sen_data if w["match_id"] == match_id])

        return obs_count > 0 or sen_count > 0

    def get_dataframes(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Return ward data as DataFrames.

        Returns:
            Tuple[pd.DataFrame, pd.DataFrame]: (obs_df, sen_df)
        """
        df_obs = pd.DataFrame(self.obs_data) if self.obs_data else pd.DataFrame()
        df_sen = pd.DataFrame(self.sen_data) if self.sen_data else pd.DataFrame()
        return df_obs, df_sen

    def extract_objectives(
        self,
        match_id: int,
        objectives: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Extract objective event times.

        Args:
            match_id: The match ID.
            objectives: List of objective event dicts.

        Returns:
            Dict[str, Any]: Column name -> time mapping for towers and Roshan.
        """
        result: Dict[str, Any] = {"match_id": match_id}

        # Max time for events that never occurred
        max_time = 3 * 60 * 60

        # Tower column names
        towers = [
            "radiant_tower1_top", "radiant_tower2_top", "radiant_tower3_top",
            "radiant_tower1_mid", "radiant_tower2_mid", "radiant_tower3_mid",
            "radiant_tower1_bot", "radiant_tower2_bot", "radiant_tower3_bot",
            "dire_tower1_top", "dire_tower2_top", "dire_tower3_top",
            "dire_tower1_mid", "dire_tower2_mid", "dire_tower3_mid",
            "dire_tower1_bot", "dire_tower2_bot", "dire_tower3_bot",
        ]

        # Initialise all towers to max time
        for tower in towers:
            result[tower] = max_time

        # Roshan kills
        rosh_count = 0
        for i in range(4):
            result[f"ROSHAN_{i}"] = max_time

        # Parse objective events
        for obj in objectives:
            obj_type = obj.get("type", "")
            key = obj.get("key", "")
            time = obj.get("time", max_time)

            if obj_type == "building_kill":
                col_name = key.replace("npc_dota_goodguys", "radiant")
                col_name = col_name.replace("npc_dota_badguys", "dire")
                if col_name in result:
                    result[col_name] = time
            elif obj_type == "CHAT_MESSAGE_ROSHAN_KILL":
                if rosh_count < 4:
                    result[f"ROSHAN_{rosh_count}"] = time
                    rosh_count += 1

        return result


# ---------------------------------------------------------------------------
# WardAnalyzer
# ---------------------------------------------------------------------------


class WardAnalyzer:
    """Ward analysis and visualisation.

    Generates scatter plots, interactive HTML pages, heatmaps, and
    statistics summaries from observer/sentry ward DataFrames.
    """

    def __init__(
        self,
        df_obs: pd.DataFrame,
        df_sen: pd.DataFrame,
        radiant_name: str = "天辉 Radiant",
        dire_name: str = "夜魇 Dire",
        match_duration: Optional[int] = None,
        radiant_players: Optional[List[Dict[str, Any]]] = None,
        dire_players: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.df_obs = df_obs.copy()
        self.df_sen = df_sen.copy()
        self.radiant_name = radiant_name
        self.dire_name = dire_name
        self.match_duration = match_duration
        self.radiant_players = radiant_players or []
        self.dire_players = dire_players or []

        # Coordinate transform (64,64) -> (0,0)
        if not self.df_obs.empty:
            self.df_obs["x"] = self.df_obs["x"] - 64
            self.df_obs["y"] = self.df_obs["y"] - 64

        if not self.df_sen.empty:
            self.df_sen["x"] = self.df_sen["x"] - 64
            self.df_sen["y"] = self.df_sen["y"] - 64

        # Load map image
        self.map_image: Optional[Any] = None
        map_path = get_map_path(MAP_VERSION)
        if map_path and HAS_PIL:
            try:
                self.map_image = Image.open(map_path)
            except Exception:
                logger.warning("Failed to load map image from %s", map_path)

        # Load ward icons (requires matplotlib)
        self.ward_icons: Dict[str, Any] = {}
        icon_dir = FIGURE_DIR
        icon_files = {
            "obs_radiant": "goodguys_observer.png",
            "obs_dire": "badguys_observer.png",
            "sen_radiant": "goodguys_sentry.png",
            "sen_dire": "badguys_sentry.png",
        }
        if HAS_MATPLOTLIB:
            for key, filename in icon_files.items():
                icon_path = os.path.join(icon_dir, filename)
                if os.path.exists(icon_path):
                    try:
                        self.ward_icons[key] = plt.imread(icon_path)
                    except Exception:
                        logger.warning("Failed to load ward icon: %s", icon_path)

        self.icon_zoom: float = 0.55

    # ------------------------------------------------------------------
    # Scatter plot
    # ------------------------------------------------------------------

    def add_ward_icon(
        self,
        ax: Any,
        x: float,
        y: float,
        icon_key: str,
    ) -> None:
        """Add a ward icon at the specified position on the axes.

        Args:
            ax: Matplotlib axes.
            x: X coordinate.
            y: Y coordinate.
            icon_key: Icon key (e.g. "obs_radiant").
        """
        if icon_key in self.ward_icons:
            img = OffsetImage(self.ward_icons[icon_key], zoom=self.icon_zoom)
            ab = AnnotationBbox(img, (x, y), frameon=False)
            ax.add_artist(ab)

    def create_icon_legend(self, ax: Any, counts: Dict[str, int]) -> None:
        """Create a custom legend with ward icons.

        Args:
            ax: Matplotlib axes.
            counts: Dict of icon_key -> count.
        """
        if not HAS_MATPLOTLIB:
            return

        legend_items: List[Any] = []
        labels: List[str] = []

        legend_config = [
            ("obs_radiant", f"{self.radiant_name} 假眼 ({{}})"),
            ("obs_dire", f"{self.dire_name} 假眼 ({{}})"),
            ("sen_radiant", f"{self.radiant_name} 真眼 ({{}})"),
            ("sen_dire", f"{self.dire_name} 真眼 ({{}})"),
        ]

        for icon_key, label_template in legend_config:
            count = counts.get(icon_key, 0)
            if icon_key in self.ward_icons:
                img = OffsetImage(self.ward_icons[icon_key], zoom=0.25)
                legend_items.append(img)
                labels.append(label_template.format(count))

        legend_y = 1.12
        legend_x_start = 0.1
        legend_spacing = 0.22

        for i, (item, label) in enumerate(zip(legend_items, labels)):
            x_pos = legend_x_start + i * legend_spacing
            ab = AnnotationBbox(
                item, (x_pos, legend_y),
                xycoords='axes fraction', frameon=False,
            )
            ax.add_artist(ab)
            ax.text(
                x_pos + 0.03, legend_y, label,
                transform=ax.transAxes,
                fontsize=9, verticalalignment='center',
            )

    def generate_scatter_plot(
        self,
        save_path: str,
        figsize: Tuple[int, int] = (12, 12),
    ) -> bool:
        """Generate a ward scatter plot on the Dota 2 minimap.

        Args:
            save_path: Output file path.
            figsize: Figure size tuple.

        Returns:
            bool: True if the plot was saved successfully.
        """
        if not HAS_MATPLOTLIB:
            logger.error("matplotlib is not available; cannot generate scatter plot")
            return False
        try:
            fig, ax = plt.subplots(figsize=figsize)

            # Display map
            if self.map_image:
                ax.imshow(self.map_image, extent=[0, 128, 0, 128])
            else:
                ax.set_facecolor("gray")

            # Count each ward type
            counts: Dict[str, int] = {
                "obs_radiant": 0, "obs_dire": 0,
                "sen_radiant": 0, "sen_dire": 0,
            }

            # Draw observer wards
            if not self.df_obs.empty:
                obs_rad = self.df_obs[self.df_obs["is_radiant"] == 1]
                obs_dir = self.df_obs[self.df_obs["is_radiant"] == 0]
                counts["obs_radiant"] = len(obs_rad)
                counts["obs_dire"] = len(obs_dir)

                for _, row in obs_rad.iterrows():
                    self.add_ward_icon(ax, row["x"], row["y"], "obs_radiant")
                for _, row in obs_dir.iterrows():
                    self.add_ward_icon(ax, row["x"], row["y"], "obs_dire")

            # Draw sentry wards
            if not self.df_sen.empty:
                sen_rad = self.df_sen[self.df_sen["is_radiant"] == 1]
                sen_dir = self.df_sen[self.df_sen["is_radiant"] == 0]
                counts["sen_radiant"] = len(sen_rad)
                counts["sen_dire"] = len(sen_dir)

                for _, row in sen_rad.iterrows():
                    self.add_ward_icon(ax, row["x"], row["y"], "sen_radiant")
                for _, row in sen_dir.iterrows():
                    self.add_ward_icon(ax, row["x"], row["y"], "sen_dire")

            ax.set_xlim(0, 128)
            ax.set_ylim(0, 128)

            # Title with match ID
            if not self.df_obs.empty and "match_id" in self.df_obs.columns:
                match_id = self.df_obs["match_id"].iloc[0]
                title = f"Dota 2 眼位分布图 - 比赛 {match_id}\n{self.radiant_name} vs {self.dire_name}"
            else:
                title = f"Dota 2 眼位分布图\n{self.radiant_name} vs {self.dire_name}"

            ax.set_title(title, pad=60)

            # Legend
            self.create_icon_legend(ax, counts)

            plt.savefig(save_path, dpi=150, bbox_inches="tight")
            plt.close()

            return True
        except Exception as e:
            logger.error("Failed to generate scatter plot: %s", e)
            return False

    # ------------------------------------------------------------------
    # Interactive HTML
    # ------------------------------------------------------------------

    def generate_interactive_html(
        self,
        save_path: str,
        obs_duration: int = 360,
        sen_duration: int = 420,
    ) -> bool:
        """Generate an interactive HTML page with time-slider ward visualisation.

        Args:
            save_path: Output HTML file path.
            obs_duration: Default observer ward lifetime in seconds.
            sen_duration: Default sentry ward lifetime in seconds.

        Returns:
            bool: True if the HTML was written successfully.
        """
        try:
            # Convert map image to base64
            map_base64 = ""
            if self.map_image and HAS_PIL:
                buffered = BytesIO()
                self.map_image.save(buffered, format="JPEG")
                map_base64 = base64.b64encode(buffered.getvalue()).decode()

            heatmap_base64 = self.generate_heatmap_base64()
            if heatmap_base64:
                heatmap_html = (
                    "<div class=\"heatmap-container\">"
                    "<div class=\"heatmap-title\">视野热力图</div>"
                    f"<img src=\"data:image/png;base64,{heatmap_base64}\" class=\"heatmap-image\">"
                    "</div>"
                )
            else:
                heatmap_html = (
                    "<div class=\"heatmap-container\">"
                    "<div class=\"heatmap-title\">视野热力图</div>"
                    "<p class=\"placeholder\">热力图生成失败</p>"
                    "</div>"
                )

            # Convert ward icons to base64
            icon_base64: Dict[str, str] = {}
            icon_dir = FIGURE_DIR
            icon_files = {
                "obs_radiant": "goodguys_observer.png",
                "obs_dire": "badguys_observer.png",
                "sen_radiant": "goodguys_sentry.png",
                "sen_dire": "badguys_sentry.png",
            }
            for key, filename in icon_files.items():
                icon_path = os.path.join(icon_dir, filename)
                if os.path.exists(icon_path):
                    with open(icon_path, "rb") as f:
                        icon_base64[key] = base64.b64encode(f.read()).decode()

            # Build roster HTML
            def format_roster(players: List[Dict[str, Any]]) -> str:
                if not players:
                    return '<li class="empty">暂无数据</li>'
                items = []
                for p in players:
                    hero_name = html.escape(str(p.get("hero", "Unknown")))
                    player_name = html.escape(str(p.get("player", "Unknown")))
                    items.append(
                        f"<li><span class=\"hero\">{hero_name}</span>"
                        f"<span class=\"player\">{player_name}</span></li>"
                    )
                return "\n".join(items)

            radiant_roster_html = format_roster(self.radiant_players)
            dire_roster_html = format_roster(self.dire_players)

            # hero_id -> player name mapping (for tooltips)
            player_by_hero_id: Dict[int, str] = {}
            for p in self.radiant_players + self.dire_players:
                hero_id = p.get("hero_id")
                if hero_id is not None:
                    player_by_hero_id[int(hero_id)] = str(p.get("player", "Unknown"))

            # Prepare ward data
            wards_data: List[Dict[str, Any]] = []
            obs_range = 1600 / 128
            sen_range = 1000 / 128

            # Build hero_id -> en_name mapping
            hero_map = build_hero_map()

            def resolve_end_time(
                row: pd.Series,
                time_val: int,
                default_duration: int,
            ) -> int:
                end_time_val: Optional[int] = None
                left_raw = row.get("left_time")
                if left_raw is not None and not pd.isna(left_raw):
                    try:
                        candidate = int(left_raw)
                    except (TypeError, ValueError):
                        candidate = None
                    if candidate is not None and candidate >= time_val:
                        end_time_val = candidate
                if end_time_val is None:
                    end_time_val = time_val + default_duration
                return end_time_val

            # Process observer wards
            if not self.df_obs.empty:
                for _, row in self.df_obs.iterrows():
                    ward_type = "obs_radiant" if row["is_radiant"] == 1 else "obs_dire"
                    hero_id = int(row.get("hero_id", 0))
                    hero_en = hero_map.get(hero_id, f"Hero {hero_id}")
                    hero_cn = get_cn_name(hero_en)
                    team_name = self.radiant_name if row["is_radiant"] == 1 else self.dire_name
                    player_name = player_by_hero_id.get(hero_id, "Unknown")
                    time_val = int(row.get("time", 0))
                    end_time = resolve_end_time(row, time_val, obs_duration)
                    wards_data.append({
                        "x": float(row["x"]),
                        "y": float(row["y"]),
                        "time": time_val,
                        "duration": obs_duration,
                        "end_time": end_time,
                        "type": ward_type,
                        "is_obs": True,
                        "range": obs_range,
                        "hero": hero_cn,
                        "team": team_name,
                        "player": player_name,
                    })

            # Process sentry wards
            if not self.df_sen.empty:
                for _, row in self.df_sen.iterrows():
                    ward_type = "sen_radiant" if row["is_radiant"] == 1 else "sen_dire"
                    hero_id = int(row.get("hero_id", 0))
                    hero_en = hero_map.get(hero_id, f"Hero {hero_id}")
                    hero_cn = get_cn_name(hero_en)
                    team_name = self.radiant_name if row["is_radiant"] == 1 else self.dire_name
                    player_name = player_by_hero_id.get(hero_id, "Unknown")
                    time_val = int(row.get("time", 0))
                    end_time = resolve_end_time(row, time_val, sen_duration)
                    wards_data.append({
                        "x": float(row["x"]),
                        "y": float(row["y"]),
                        "time": time_val,
                        "duration": sen_duration,
                        "end_time": end_time,
                        "type": ward_type,
                        "is_obs": False,
                        "range": sen_range,
                        "hero": hero_cn,
                        "team": team_name,
                        "player": player_name,
                    })

            # Time range
            all_times = [w["time"] for w in wards_data]
            min_time = -90
            if self.match_duration and self.match_duration > 0:
                max_time = int(self.match_duration)
            else:
                max_time = (
                    max(all_times) + max(obs_duration, sen_duration)
                    if all_times
                    else 3600
                )

            # Match ID
            match_id = ""
            if not self.df_obs.empty and "match_id" in self.df_obs.columns:
                match_id = str(self.df_obs["match_id"].iloc[0])

            # Player filter list
            player_list = sorted({w.get("player", "Unknown") for w in wards_data})
            player_filter_html = "\n".join(
                f"<label class=\"filter-item\">"
                f"<input type=\"checkbox\" name=\"playerFilter\" "
                f"value=\"{html.escape(player)}\" checked> "
                f"{html.escape(player)}</label>"
                for player in player_list
            )

            # Generate HTML
            html_content = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dota 2 眼位时间线 - 比赛 {match_id}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; background: #0b0b0b; min-height: 100vh; padding: 20px; color: #e6e6e6; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ text-align: center; margin-bottom: 10px; color: #f0f0f0; letter-spacing: 0.5px; }}
        .teams {{ text-align: center; margin-bottom: 10px; font-size: 18px; color: #d7c27a; font-weight: 600; }}
        .map-layout {{ display: flex; flex-direction: column; gap: 12px; align-items: stretch; }}
        .team-row {{ display: flex; gap: 12px; align-items: stretch; flex-wrap: nowrap; overflow-x: auto; }}
        .team-card {{ background: #121212; border-radius: 12px; padding: 10px 12px; border: 1px solid #1f1f1f; min-width: 0; flex: 1 1 0; }}
        .team-title {{ font-size: 13px; font-weight: 600; margin-bottom: 6px; color: #f0f0f0; }}
        .roster-list {{ list-style: none; font-size: 11px; }}
        .roster-list li {{ display: flex; justify-content: space-between; align-items: center; padding: 3px 0; border-bottom: 1px dashed rgba(255,255,255,0.08); gap: 10px; min-width: 0; }}
        .roster-list li:last-child {{ border-bottom: none; }}
        .roster-list .hero {{ color: #d7c27a; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .roster-list .player {{ color: #bdbdbd; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .roster-list .empty {{ color: #999; justify-content: center; }}
        .team-card.radiant {{ border-left: 4px solid #2e7d32; }}
        .team-card.dire {{ border-left: 4px solid #b23b3b; }}
        .team-card .badge {{ font-size: 12px; padding: 2px 8px; border-radius: 999px; background: #1a1a1a; color: #bdbdbd; margin-left: 6px; border: 1px solid #2a2a2a; }}
        @media (max-width: 980px) {{
            .team-row {{ gap: 8px; }}
        }}
        .map-container {{ position: relative; width: 100%; max-width: 800px; margin: 0 auto; border: 2px solid #2a2a2a; border-radius: 10px; overflow: hidden; box-shadow: 0 6px 18px rgba(0,0,0,0.45); }}
        .map-image {{ width: 100%; display: block; }}
        .ward {{ position: absolute; transform: translate(-50%, -50%); transition: opacity 0.2s ease; pointer-events: auto; z-index: 10; cursor: pointer; }}
        .ward img {{ width: 26px; height: 26px; }}
        .ward.hidden {{ opacity: 0; pointer-events: none; }}
        .ward-range {{ position: absolute; transform: translate(-50%, -50%); border-radius: 50%; pointer-events: none; z-index: 5; opacity: 0.95; }}
        .ward-range.range-obs {{ border: 1px dashed rgba(88, 166, 255, 0.75); background: rgba(88, 166, 255, 0.16); }}
        .ward-range.range-sen {{ border: 1px dashed rgba(255, 122, 122, 0.75); background: rgba(255, 122, 122, 0.16); }}
        .ward-range.hidden {{ opacity: 0; }}
        .tooltip {{ position: fixed; background: rgba(12,12,12,0.95); color: #f0f0f0; padding: 10px 14px; border-radius: 8px; font-size: 13px; z-index: 1000; pointer-events: none; box-shadow: 0 4px 12px rgba(0,0,0,0.6); border: 1px solid #2a2a2a; white-space: nowrap; }}
        .tooltip .hero {{ color: #d7c27a; font-weight: 600; font-size: 14px; }}
        .tooltip .player {{ color: #ddd; font-size: 12px; }}
        .tooltip .team {{ color: #aaa; font-size: 12px; }}
        .tooltip .time {{ color: #9ecbff; }}
        .tooltip .ward-type {{ color: #98c379; }}
        .controls {{ width: 100%; max-width: 800px; margin: 16px auto; background: #121212; padding: 10px 12px; border-radius: 10px; border: 1px solid #1f1f1f; }}
        .time-display {{ text-align: center; font-size: 18px; font-weight: 600; margin-bottom: 8px; color: #d7c27a; }}
        .slider-container {{ display: flex; align-items: center; gap: 8px; }}
        .slider {{ flex: 1; -webkit-appearance: none; height: 6px; border-radius: 6px; background: #2a2a2a; outline: none; cursor: pointer; }}
        .slider::-webkit-slider-thumb {{ -webkit-appearance: none; width: 14px; height: 14px; border-radius: 50%; background: #d7c27a; cursor: pointer; box-shadow: 0 2px 6px rgba(0,0,0,0.5); }}
        .time-label {{ font-size: 11px; color: #aaa; min-width: 46px; }}
        .stats {{ display: flex; justify-content: center; gap: 40px; margin-top: 15px; font-size: 14px; }}
        .stat-item {{ text-align: center; }}
        .stat-value {{ font-size: 24px; font-weight: 600; color: #d7c27a; }}
        .filters {{ margin-top: 12px; background: rgba(255,255,255,0.04); padding: 10px 12px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.08); }}
        .filters-header {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px; }}
        .filters-title {{ font-size: 14px; color: #f0f0f0; font-weight: 600; }}
        .filter-actions {{ display: flex; gap: 8px; }}
        .filter-button {{ background: #1a1a1a; color: #cfcfcf; border: 1px solid #2a2a2a; padding: 4px 10px; border-radius: 999px; font-size: 12px; cursor: pointer; }}
        .filter-button:hover {{ background: #242424; }}
        .filter-list {{ display: flex; flex-wrap: wrap; gap: 8px 12px; }}
        .filter-item {{ font-size: 12px; color: #ddd; display: flex; align-items: center; gap: 6px; }}
        .filter-item input {{ accent-color: #d7c27a; }}
        .report {{ margin-top: 22px; background: #121212; border: 1px solid #1f1f1f; border-radius: 12px; padding: 16px 18px; }}
        .report h2 {{ font-size: 18px; margin-bottom: 10px; color: #f6f6f6; }}
        .report .report-section {{ margin-bottom: 12px; }}
        .report .report-section:last-child {{ margin-bottom: 0; }}
        .report p {{ line-height: 1.6; color: #e0e0e0; }}
        .report .tag {{ display: inline-block; padding: 2px 8px; border-radius: 999px; background: #1a1a1a; font-size: 12px; color: #d7c27a; margin-right: 6px; border: 1px solid #2a2a2a; }}
        .report table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }}
        .report th, .report td {{ padding: 8px 6px; border-bottom: 1px solid rgba(255,255,255,0.08); text-align: left; }}
        .report th {{ color: #d7c27a; font-weight: 600; }}
        .report .placeholder {{ color: #aaa; }}
        .heatmap-container {{ max-width: 800px; margin: 14px auto 0; background: #121212; padding: 10px 12px; border-radius: 10px; border: 1px solid #1f1f1f; }}
        .heatmap-title {{ font-size: 13px; color: #f0f0f0; margin-bottom: 8px; }}
        .heatmap-image {{ width: 100%; display: block; border-radius: 8px; border: 1px solid #2a2a2a; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Dota 2 眼位时间线</h1>
        <div class="teams">🟢 {self.radiant_name} vs {self.dire_name} 🔴</div>
        <p style="text-align: center; margin-bottom: 15px; color: #aaa;">比赛 ID: {match_id}</p>

        <div class="map-layout">
            <div class="team-row">
                <div class="team-card radiant">
                    <div class="team-title">🟢 {self.radiant_name} 阵容<span class="badge">Radiant</span></div>
                    <ul class="roster-list">
                        {radiant_roster_html}
                    </ul>
                </div>
                <div class="team-card dire">
                    <div class="team-title">🔴 {self.dire_name} 阵容<span class="badge">Dire</span></div>
                    <ul class="roster-list">
                        {dire_roster_html}
                    </ul>
                </div>
            </div>
            <div class="map-container" id="mapContainer">
                <img src="data:image/jpeg;base64,{map_base64}" class="map-image" id="mapImage">
            </div>
            <div class="controls">
                <div class="time-display" id="timeDisplay">00:00</div>

                <div class="slider-container">
                    <span class="time-label" id="minTimeLabel">{min_time // 60}:{min_time % 60:02d}</span>
                    <input type="range" class="slider" id="timeSlider" min="{min_time}" max="{max_time}" value="{min_time}">
                    <span class="time-label" id="maxTimeLabel">{max_time // 60}:{max_time % 60:02d}</span>
                </div>

                <div class="stats">
                    <div class="stat-item">
                        <div class="stat-value" id="activeObs">0</div>
                        <div>当前假眼</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value" id="activeSen">0</div>
                        <div>当前真眼</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value" id="totalWards">{len(wards_data)}</div>
                        <div>总眼位数</div>
                    </div>
                </div>

                <div class="filters">
                    <div class="filters-header">
                        <div class="filters-title">按选手筛选眼位</div>
                        <div class="filter-actions">
                            <button class="filter-button" id="selectAllPlayers">全选</button>
                            <button class="filter-button" id="clearAllPlayers">清空</button>
                        </div>
                    </div>
                    <div class="filter-list" id="playerFilters">
                        {player_filter_html}
                    </div>
                </div>
            </div>
            {heatmap_html}
        </div>

        <section class="report" id="analysisReport">
            <h2>视野分析报告</h2>
            <div class="report-content" id="reportContent">
                <!-- WARD_REPORT_START -->
                <p class="placeholder">视野分析报告将在生成后显示。</p>
                <!-- WARD_REPORT_END -->
            </div>
        </section>
    </div>

    <script>
        const wardsData = {json.dumps(wards_data)};
        const MIN_TIME = {min_time};
        const icons = {{
            'obs_radiant': 'data:image/png;base64,{icon_base64.get("obs_radiant", "")}',
            'obs_dire': 'data:image/png;base64,{icon_base64.get("obs_dire", "")}',
            'sen_radiant': 'data:image/png;base64,{icon_base64.get("sen_radiant", "")}',
            'sen_dire': 'data:image/png;base64,{icon_base64.get("sen_dire", "")}'
        }};

        const mapContainer = document.getElementById('mapContainer');
        const timeSlider = document.getElementById('timeSlider');
        const timeDisplay = document.getElementById('timeDisplay');
        const activeObs = document.getElementById('activeObs');
        const activeSen = document.getElementById('activeSen');
        const selectAllPlayers = document.getElementById('selectAllPlayers');
        const clearAllPlayers = document.getElementById('clearAllPlayers');
        const playerFilterInputs = document.querySelectorAll('input[name="playerFilter"]');

        let wardElements = [];
        let rangeElements = [];

        // Create tooltip element
        const tooltip = document.createElement('div');
        tooltip.className = 'tooltip';
        tooltip.style.display = 'none';
        document.body.appendChild(tooltip);

        function createWardElements() {{
            wardsData.forEach((ward, index) => {{
                const xPercent = (ward.x / 128) * 100;
                const yPercent = (1 - ward.y / 128) * 100;
                const rangePercent = (ward.range / 128) * 100;

                const range = document.createElement('div');
                range.className = `ward-range ${{ward.is_obs ? 'range-obs' : 'range-sen'}} hidden`;
                range.style.left = xPercent + '%';
                range.style.top = yPercent + '%';
                range.style.width = (rangePercent * 2) + '%';
                range.style.height = (rangePercent * 2) + '%';
                mapContainer.appendChild(range);
                rangeElements.push(range);

                const div = document.createElement('div');
                div.className = 'ward hidden';
                div.dataset.index = index;

                const img = document.createElement('img');
                img.src = icons[ward.type];
                div.appendChild(img);

                div.style.left = xPercent + '%';
                div.style.top = yPercent + '%';

                // Add mouse hover events
                div.addEventListener('mouseenter', (e) => {{
                    const wardType = ward.is_obs ? '假眼 (Observer)' : '真眼 (Sentry)';
                    const timeStr = formatTime(ward.time);
                    tooltip.innerHTML = `
                        <div class="hero">${{ward.hero}}</div>
                        <div class="player">选手: ${{ward.player}}</div>
                        <div class="team">${{ward.team}}</div>
                        <div class="ward-type">${{wardType}}</div>
                        <div class="time">放置时间: ${{timeStr}}</div>
                    `;
                    tooltip.style.display = 'block';
                }});

                div.addEventListener('mousemove', (e) => {{
                    tooltip.style.left = (e.clientX + 15) + 'px';
                    tooltip.style.top = (e.clientY + 15) + 'px';
                }});

                div.addEventListener('mouseleave', () => {{
                    tooltip.style.display = 'none';
                }});

                mapContainer.appendChild(div);
                wardElements.push(div);
            }});
        }}

        function getSelectedPlayers() {{
            const selected = [];
            playerFilterInputs.forEach((input) => {{
                if (input.checked) {{
                    selected.push(input.value);
                }}
            }});
            return selected;
        }}

        function updateWards(currentTime) {{
            let obsCount = 0;
            let senCount = 0;
            const showAll = currentTime <= MIN_TIME;
            const selectedPlayers = getSelectedPlayers();
            const hasPlayerFilter = selectedPlayers.length > 0;
            const playerSet = new Set(selectedPlayers);

            wardsData.forEach((ward, index) => {{
                const endTime = (ward.end_time !== undefined && ward.end_time !== null)
                    ? ward.end_time
                    : ((ward.duration !== undefined && ward.duration !== null) ? ward.time + ward.duration : null);
                const isActive = showAll || (currentTime >= ward.time && (endTime === null || currentTime < endTime));
                const matchesPlayer = !hasPlayerFilter || playerSet.has(ward.player);

                if (isActive && matchesPlayer) {{
                    wardElements[index].classList.remove('hidden');
                    rangeElements[index].classList.remove('hidden');
                    if (ward.is_obs) obsCount++;
                    else senCount++;
                }} else {{
                    wardElements[index].classList.add('hidden');
                    rangeElements[index].classList.add('hidden');
                }}
            }});

            activeObs.textContent = obsCount;
            activeSen.textContent = senCount;
        }}

        function formatTime(seconds) {{
            const sign = seconds < 0 ? '-' : '';
            const absSeconds = Math.abs(seconds);
            const mins = Math.floor(absSeconds / 60);
            const secs = absSeconds % 60;
            return sign + mins + ':' + secs.toString().padStart(2, '0');
        }}

        timeSlider.addEventListener('input', function() {{
            const currentTime = parseInt(this.value);
            timeDisplay.textContent = currentTime <= MIN_TIME ? '全部' : formatTime(currentTime);
            updateWards(currentTime);
        }});


        playerFilterInputs.forEach((input) => {{
            input.addEventListener('change', () => {{
                updateWards(parseInt(timeSlider.value));
            }});
        }});

        selectAllPlayers.addEventListener('click', () => {{
            playerFilterInputs.forEach((input) => {{
                input.checked = true;
            }});
            updateWards(parseInt(timeSlider.value));
        }});

        clearAllPlayers.addEventListener('click', () => {{
            playerFilterInputs.forEach((input) => {{
                input.checked = false;
            }});
            updateWards(parseInt(timeSlider.value));
        }});

        createWardElements();
        updateWards(parseInt(timeSlider.value));
        timeDisplay.textContent = parseInt(timeSlider.value) <= MIN_TIME ? '全部' : formatTime(parseInt(timeSlider.value));
    </script>
</body>
</html>'''

            # Save HTML file
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            return True
        except Exception as e:
            logger.error("Failed to generate interactive HTML: %s", e)
            return False

    # ------------------------------------------------------------------
    # Heatmap generation
    # ------------------------------------------------------------------

    def generate_heatmap_base64(
        self,
        sigma: float = 5.0,
        alpha: float = 0.65,
        ward_type: Optional[str] = None,
    ) -> str:
        """Generate a heatmap and return base64-encoded PNG.

        Args:
            sigma: Gaussian blur sigma in 0-128 coordinate units.
            alpha: Maximum heatmap alpha (0-1).
            ward_type: "obs"/"sen" to filter; None means all.

        Returns:
            str: Base64-encoded PNG string; empty string on failure.
        """
        if self.map_image is None or not HAS_PIL:
            return ""

        width, height = self.map_image.size
        canvas = np.zeros((height, width), dtype=np.float32)
        point_weight = 1.0

        # Validate ward_type
        if ward_type not in (None, "obs", "sen"):
            return ""

        # Collect ward coordinates (already in 0-128 range)
        points: List[np.ndarray] = []
        if ward_type in (None, "obs") and not self.df_obs.empty:
            points.extend(self.df_obs[["x", "y"]].to_numpy())
        if ward_type in (None, "sen") and not self.df_sen.empty:
            points.extend(self.df_sen[["x", "y"]].to_numpy())
        if not points:
            return ""

        # Convert to pixel coordinates and accumulate
        x_scale = (width - 1) / 128.0
        y_scale = (height - 1) / 128.0
        for x_val, y_val in points:
            if not (np.isfinite(x_val) and np.isfinite(y_val)):
                continue
            x_val = np.clip(x_val, 0, 128)
            y_val = np.clip(y_val, 0, 128)
            px = int(round(x_val * x_scale))
            # Y-axis flip: game y=0 is bottom, image y=0 is top
            py = int(round((128 - y_val) * y_scale))
            if 0 <= px < width and 0 <= py < height:
                canvas[py, px] += point_weight

        # Gaussian blur (sigma in pixel scale)
        sigma_px = sigma * (width / 128.0)

        if HAS_OPENCV:
            kernel_size = int(round(sigma_px * 6))
            if kernel_size % 2 == 0:
                kernel_size += 1
            kernel_size = max(3, min(kernel_size, min(width, height) - 1))
            if kernel_size % 2 == 0:
                kernel_size -= 1
            blurred = cv2.GaussianBlur(canvas, (kernel_size, kernel_size), sigma_px)
        else:
            blurred = gaussian_blur(canvas, sigma_px)

        # Normalise to 0-1
        max_val = blurred.max()
        if max_val > 0:
            blurred = blurred / max_val

        # Pseudo-colour (JET colormap)
        if HAS_OPENCV:
            heat_color = cv2.applyColorMap(
                (blurred * 255).astype(np.uint8),
                cv2.COLORMAP_JET,
            )
            heat_color = cv2.cvtColor(heat_color, cv2.COLOR_BGR2RGB)
        else:
            if not HAS_MATPLOTLIB:
                logger.error("Neither cv2 nor matplotlib available for heatmap colouring")
                return ""
            cmap = plt.get_cmap("jet")
            heat_color = (cmap(blurred)[:, :, :3] * 255).astype(np.uint8)

        # Overlay: only blend where there is heat
        base_image = np.array(self.map_image.convert("RGB"))
        alpha_map = np.clip(blurred * alpha, 0, alpha)
        overlay = (
            base_image * (1 - alpha_map[..., None]) + heat_color * alpha_map[..., None]
        ).astype(np.uint8)

        try:
            output = Image.fromarray(overlay)
            buffered = BytesIO()
            output.save(buffered, format="PNG")
            return base64.b64encode(buffered.getvalue()).decode()
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Ward points image
    # ------------------------------------------------------------------

    def generate_ward_points_base64(self) -> str:
        """Generate a ward points image overlaid on the map, as base64 PNG.

        Returns:
            str: Base64-encoded PNG string; empty string on failure.
        """
        if self.map_image is None or not HAS_PIL:
            return ""

        try:
            base = self.map_image.convert("RGBA")
            width, height = base.size
            overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))

            icon_dir = FIGURE_DIR
            icon_files = {
                "obs_radiant": "goodguys_observer.png",
                "obs_dire": "badguys_observer.png",
                "sen_radiant": "goodguys_sentry.png",
                "sen_dire": "badguys_sentry.png",
            }

            # Icon size scales with map size (baseline 800px)
            icon_size = max(16, int(round(width * 26 / 800)))

            icon_cache: Dict[str, Any] = {}
            for key, filename in icon_files.items():
                icon_path = os.path.join(icon_dir, filename)
                if os.path.exists(icon_path):
                    try:
                        icon = Image.open(icon_path).convert("RGBA")
                        if icon_size > 0:
                            icon = icon.resize((icon_size, icon_size), Image.LANCZOS)
                        icon_cache[key] = icon
                    except Exception:
                        pass

            def paste_icon(x_val: float, y_val: float, icon_key: str) -> None:
                icon = icon_cache.get(icon_key)
                if icon is None:
                    return
                x_val = float(np.clip(x_val, 0, 128))
                y_val = float(np.clip(y_val, 0, 128))
                px = x_val * (width - 1) / 128.0
                py = (128 - y_val) * (height - 1) / 128.0
                left = int(round(px - icon.width / 2))
                top = int(round(py - icon.height / 2))
                overlay.alpha_composite(icon, (left, top))

            if not self.df_obs.empty:
                for _, row in self.df_obs.iterrows():
                    x_val = row.get("x")
                    y_val = row.get("y")
                    if not (np.isfinite(x_val) and np.isfinite(y_val)):
                        continue
                    icon_key = "obs_radiant" if int(row.get("is_radiant", 0)) == 1 else "obs_dire"
                    paste_icon(float(x_val), float(y_val), icon_key)

            if not self.df_sen.empty:
                for _, row in self.df_sen.iterrows():
                    x_val = row.get("x")
                    y_val = row.get("y")
                    if not (np.isfinite(x_val) and np.isfinite(y_val)):
                        continue
                    icon_key = "sen_radiant" if int(row.get("is_radiant", 0)) == 1 else "sen_dire"
                    paste_icon(float(x_val), float(y_val), icon_key)

            combined = Image.alpha_composite(base, overlay).convert("RGB")
            buffered = BytesIO()
            combined.save(buffered, format="PNG")
            return base64.b64encode(buffered.getvalue()).decode()
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Statistics summary
    # ------------------------------------------------------------------

    def get_stats_summary(self) -> str:
        """Get a text statistics summary.

        Returns:
            str: Multi-line statistics summary text.
        """
        lines: List[str] = ["# 📊 眼位数据统计\n"]

        # Match ID and team info
        if not self.df_obs.empty and "match_id" in self.df_obs.columns:
            match_id = self.df_obs["match_id"].iloc[0]
            lines.append(f"🏆 比赛ID: {match_id}")
            lines.append(f"🟢 {self.radiant_name} vs {self.dire_name} 🔴\n")

        # Team observer ward stats
        if not self.df_obs.empty:
            obs_rad = len(self.df_obs[self.df_obs["is_radiant"] == 1])
            obs_dir = len(self.df_obs[self.df_obs["is_radiant"] == 0])
            lines.append(f"\n假眼总计: {len(self.df_obs)}")
            lines.append(f"   {self.radiant_name}: {obs_rad} 个")
            lines.append(f"   {self.dire_name}: {obs_dir} 个")

        # Team sentry ward stats
        if not self.df_sen.empty:
            sen_rad = len(self.df_sen[self.df_sen["is_radiant"] == 1])
            sen_dir = len(self.df_sen[self.df_sen["is_radiant"] == 0])
            lines.append(f"\n真眼总计: {len(self.df_sen)}")
            lines.append(f"   {self.radiant_name}: {sen_rad} 个")
            lines.append(f"   {self.dire_name}: {sen_dir} 个")

        # Time distribution
        if not self.df_obs.empty:
            early_wards = len(self.df_obs[self.df_obs["time"] <= 600])
            mid_wards = len(self.df_obs[(self.df_obs["time"] > 600) & (self.df_obs["time"] <= 1800)])
            late_wards = len(self.df_obs[self.df_obs["time"] > 1800])

            lines.append(f"\n⏰ 眼位时间分布:")
            lines.append(f"   前10分钟: {early_wards} 个")
            lines.append(f"   10-30分钟: {mid_wards} 个")
            lines.append(f"   30分钟后: {late_wards} 个")

        return "\n".join(lines)
