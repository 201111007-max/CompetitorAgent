"""Hero Chinese name mapping and rank formatting utilities.

Extracts and refactors hero name / rank formatting logic from dota2_fastmcp.py
(lines 111-165, 559-601). Provides bidirectional hero name lookups and rank
tier display formatting with bilingual (EN/CN) output.

Data is loaded lazily from ``data/heroes_cn.json`` (relative to the
dota_helper project root) with an embedded fallback dictionary.
"""

import json
import logging
import os
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rank tier constants
# ---------------------------------------------------------------------------

RANK_TIER_MAP: Dict[int, Tuple[str, str]] = {
    1: ("Herald", "先锋"),
    2: ("Guardian", "卫士"),
    3: ("Crusader", "中军"),
    4: ("Archon", "统帅"),
    5: ("Legend", "传奇"),
    6: ("Ancient", "万古"),
    7: ("Divine", "超凡"),
    8: ("Immortal", "冠绝"),
}

# ---------------------------------------------------------------------------
# Embedded fallback hero CN names (en_name -> cn_name)
# Used when the external JSON file cannot be loaded.
# ---------------------------------------------------------------------------

_FALLBACK_HERO_CN: Dict[str, str] = {
    "Anti-Mage": "敌法师",
    "Axe": "斧王",
    "Bane": "祸乱之源",
    "Bloodseeker": "血魔",
    "Crystal Maiden": "水晶室女",
    "Drow Ranger": "卓尔游侠",
    "Earthshaker": "撼地者",
    "Juggernaut": "主宰",
    "Mirana": "米拉娜",
    "Morphling": "变体精灵",
    "Shadow Fiend": "影魔",
    "Phantom Lancer": "幻影长矛手",
    "Puck": "帕克",
    "Pudge": "帕吉",
    "Razor": "雷泽",
    "Sand King": "沙王",
    "Storm Spirit": "风暴之灵",
    "Sven": "斯温",
    "Tiny": "小小",
    "Vengeful Spirit": "复仇之魂",
    "Windranger": "风行者",
    "Zeus": "宙斯",
    "Kunkka": "昆卡",
    "Lina": "莉娜",
    "Lion": "莱恩",
    "Shadow Shaman": "暗影萨满",
    "Slardar": "斯拉达",
    "Tidehunter": "潮汐猎人",
    "Witch Doctor": "巫医",
    "Lich": "巫妖",
    "Riki": "力丸",
    "Enigma": "谜团",
    "Tinker": "修补匠",
    "Sniper": "狙击手",
    "Necrophos": "瘟疫法师",
    "Warlock": "术士",
    "Beastmaster": "兽王",
    "Queen of Pain": "痛苦女王",
    "Venomancer": "剧毒术士",
    "Faceless Void": "虚空假面",
    "Wraith King": "冥魂大帝",
    "Death Prophet": "死亡先知",
    "Phantom Assassin": "幻影刺客",
    "Pugna": "帕格纳",
    "Templar Assassin": "圣堂刺客",
    "Viper": "冥界亚龙",
    "Luna": "露娜",
    "Dragon Knight": "龙骑士",
    "Dazzle": "戴泽",
    "Clockwerk": "发条技师",
    "Leshrac": "拉席克",
    "Nature's Prophet": "自然先知",
    "Lifestealer": "噬魂鬼",
    "Dark Seer": "黑暗贤者",
    "Clinkz": "克林克兹",
    "Omniknight": "全能骑士",
    "Enchantress": "魅惑魔女",
    "Huskar": "哈斯卡",
    "Night Stalker": "暗夜魔王",
    "Broodmother": "育母蜘蛛",
    "Bounty Hunter": "赏金猎人",
    "Weaver": "编织者",
    "Jakiro": "杰奇洛",
    "Batrider": "蝙蝠骑士",
    "Chen": "陈",
    "Spectre": "幽鬼",
    "Ancient Apparition": "远古冰魄",
    "Doom": "末日使者",
    "Ursa": "熊战士",
    "Spirit Breaker": "裂魂人",
    "Gyrocopter": "矮人直升机",
    "Alchemist": "炼金术士",
    "Invoker": "祈求者",
    "Silencer": "沉默术士",
    "Outworld Destroyer": "殁境神蚀者",
    "Lycan": "狼人",
    "Brewmaster": "酒仙",
    "Shadow Demon": "暗影恶魔",
    "Lone Druid": "独行德鲁伊",
    "Chaos Knight": "混沌骑士",
    "Meepo": "米波",
    "Treant Protector": "树精卫士",
    "Ogre Magi": "食人魔魔法师",
    "Undying": "不朽尸王",
    "Rubick": "拉比克",
    "Disruptor": "干扰者",
    "Nyx Assassin": "司夜刺客",
    "Naga Siren": "娜迦海妖",
    "Keeper of the Light": "光之守卫",
    "Io": "艾欧",
    "Visage": "维萨吉",
    "Slark": "斯拉克",
    "Medusa": "美杜莎",
    "Troll Warlord": "巨魔战将",
    "Centaur Warrunner": "半人马战行者",
    "Magnus": "马格纳斯",
    "Timbersaw": "伐木机",
    "Bristleback": "钢背兽",
    "Tusk": "巨牙海民",
    "Skywrath Mage": "天怒法师",
    "Abaddon": "亚巴顿",
    "Elder Titan": "上古巨神",
    "Legion Commander": "军团指挥官",
    "Techies": "工程师",
    "Ember Spirit": "灰烬之灵",
    "Earth Spirit": "大地之灵",
    "Underlord": "孽主",
    "Terrorblade": "恐怖利刃",
    "Phoenix": "凤凰",
    "Oracle": "神谕者",
    "Winter Wyvern": "寒冬飞龙",
    "Arc Warden": "天穹守望者",
    "Monkey King": "齐天大圣",
    "Dark Willow": "邪影芳灵",
    "Pangolier": "石鳞剑士",
    "Grimstroke": "天涯墨客",
    "Hoodwink": "森海飞霞",
    "Void Spirit": "虚无之灵",
    "Snapfire": "电炎绝手",
    "Mars": "玛尔斯",
    "Dawnbreaker": "破晓辰星",
    "Marci": "玛西",
    "Primal Beast": "獸",
    "Muerta": "琼英碧灵",
    "Ringmaster": "百戏大王",
    "Kez": "凯",
}

# ---------------------------------------------------------------------------
# Lazy-loaded lookup tables
# ---------------------------------------------------------------------------

_hero_cn_by_en: Optional[Dict[str, str]] = None
_hero_by_id: Optional[Dict[int, Dict[str, str]]] = None


def _resolve_data_dir() -> str:
    """Resolve the dota_helper project root and return the data directory.

    Searches upward from this file's location for a ``data/heroes_cn.json``
    file, falling back to a sibling ``data/`` directory of the package root.
    """
    # Start from this file's directory and walk up
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(10):  # safety bound
        candidate = os.path.join(current, "data", "heroes_cn.json")
        if os.path.isfile(candidate):
            return os.path.join(current, "data")
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    # Fallback: assume project root is 3 levels up from this file
    # (helpers/ -> mcp_server/ -> dota_helper/)
    fallback = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "data")
    )
    return fallback


def _load_hero_data() -> Tuple[Dict[str, str], Dict[int, Dict[str, str]]]:
    """Load hero data from JSON and build lookup dictionaries.

    Returns:
        A tuple of (en_name -> cn_name, hero_id -> {"en": ..., "cn": ...}).
    """
    cn_by_en: Dict[str, str] = {}
    by_id: Dict[int, Dict[str, str]] = {}

    data_dir = _resolve_data_dir()
    json_path = os.path.join(data_dir, "heroes_cn.json")

    raw_data: Optional[Dict[str, Dict[str, str]]] = None
    if os.path.isfile(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                raw_data = json.load(fh)
            logger.debug("Loaded hero CN names from %s", json_path)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load %s: %s; using embedded fallback", json_path, exc)

    if raw_data is None:
        # Build from embedded fallback (no hero_id mapping available)
        cn_by_en = dict(_FALLBACK_HERO_CN)
        logger.info("Using embedded fallback hero CN names (%d entries)", len(cn_by_en))
        return cn_by_en, by_id

    # Parse the JSON format: {"103": {"cn": "上古巨神", "en": "Elder Titan"}, ...}
    for hero_id_str, names in raw_data.items():
        try:
            hero_id = int(hero_id_str)
        except (ValueError, TypeError):
            logger.debug("Skipping non-integer hero_id key: %s", hero_id_str)
            continue

        en_name = names.get("en", "")
        cn_name = names.get("cn", "")
        if en_name and cn_name:
            cn_by_en[en_name] = cn_name
            by_id[hero_id] = {"en": en_name, "cn": cn_name}

    # Fill any gaps from the fallback dictionary
    for en_name, cn_name in _FALLBACK_HERO_CN.items():
        cn_by_en.setdefault(en_name, cn_name)

    logger.debug("Hero lookup built: %d by-en, %d by-id", len(cn_by_en), len(by_id))
    return cn_by_en, by_id


def _ensure_loaded() -> None:
    """Ensure hero lookup tables are populated (lazy init)."""
    global _hero_cn_by_en, _hero_by_id
    if _hero_cn_by_en is None:
        _hero_cn_by_en, _hero_by_id = _load_hero_data()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_cn_name(en_name: str) -> str:
    """Get the Chinese name for a hero given its English name.

    Args:
        en_name: The English hero name (e.g. ``"Anti-Mage"``).

    Returns:
        The Chinese name if found, otherwise the original English name.
    """
    _ensure_loaded()
    assert _hero_cn_by_en is not None  # guaranteed after _ensure_loaded
    return _hero_cn_by_en.get(en_name, en_name)


def get_hero_display_name(hero_id: int) -> str:
    """Get a bilingual display name for a hero given its ID.

    The returned format is ``"中文名 (English Name)"``, e.g.
    ``"敌法师 (Anti-Mage)"``.

    Args:
        hero_id: The numeric hero ID.

    Returns:
        A bilingual display string. Falls back to ``"Unknown Hero (ID)"``
        when the hero ID is not found.
    """
    _ensure_loaded()
    assert _hero_by_id is not None  # guaranteed after _ensure_loaded
    info = _hero_by_id.get(hero_id)
    if info:
        return f"{info['cn']} ({info['en']})"
    return f"Unknown Hero ({hero_id})"


def get_rank_display(rank_tier: Any) -> Optional[str]:
    """Format a rank tier value into a bilingual display string.

    The rank_tier integer encodes both tier and star: ``tier * 10 + star``.
    For example, ``65`` means **Legend 5**.

    Args:
        rank_tier: The rank tier value (e.g. ``65``). Accepts ``None``,
            strings, or numeric types.

    Returns:
        A formatted string like ``"Legend 5（传奇5星）"`` or ``"Immortal（冠绝）"``,
        or ``None`` if the input is ``None`` or maps to an invalid tier.
    """
    if rank_tier is None:
        return None
    try:
        rank_float = float(rank_tier)
        rank_int = int(round(rank_float))
    except (TypeError, ValueError):
        return str(rank_tier)
    if rank_int <= 0:
        return None
    tier = rank_int // 10
    star = rank_int % 10
    # Immortal and above have no star
    if tier >= 8:
        en, cn = RANK_TIER_MAP.get(8, ("Immortal", "冠绝"))
        return f"{en}（{cn}）"
    entry = RANK_TIER_MAP.get(tier)
    if not entry:
        return str(rank_tier)
    en, cn = entry
    if star <= 0:
        return f"{en}（{cn}）"
    return f"{en} {star}（{cn}{star}星）"


def get_rank_bin_display(bin_name: Any, bin_id: Any = None) -> str:
    """Format a rank bin name/id into a bilingual display string.

    Attempts to resolve the rank from ``bin_id`` first (when it is a valid
    integer key in :data:`RANK_TIER_MAP`), then falls back to matching the
    English tier name within ``bin_name``.

    Args:
        bin_name: The human-readable bin name (e.g. ``"Legend"`` or
            ``"legend_bracket"``).
        bin_id: An optional numeric rank tier ID (1-8).

    Returns:
        A formatted string like ``"Legend（传奇）"`` or the raw
        ``bin_name`` string when no mapping is found.
    """
    # Try matching by numeric bin_id first
    if bin_id is not None:
        try:
            bin_int = int(bin_id)
        except (TypeError, ValueError):
            bin_int = None
        if bin_int is not None and bin_int in RANK_TIER_MAP:
            en, cn = RANK_TIER_MAP[bin_int]
            return f"{en}（{cn}）"

    # Fall back to text matching against English tier names
    name_str = str(bin_name) if bin_name is not None else "N/A"
    for en, cn in RANK_TIER_MAP.values():
        if en.lower() in name_str.lower():
            return f"{en}（{cn}）"
    return name_str
