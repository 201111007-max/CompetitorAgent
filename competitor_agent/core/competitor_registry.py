"""竞品注册表：预注册常用 AI Coding Agent，未知竞品走通用采集"""
from __future__ import annotations

from competitor_agent.domain_types.competitor import Competitor

COMPETITOR_REGISTRY: dict[str, Competitor] = {
    "claude-code": Competitor(
        name="claude-code",
        aliases=["claude", "claude code", "anthropic claude code"],
        official_links={
            "home": "https://www.anthropic.com/claude-code",
            "docs": "https://docs.anthropic.com/en/docs/claude-code",
            "pricing": "https://www.anthropic.com/pricing",
        },
    ),
    "cursor": Competitor(
        name="cursor",
        aliases=["anysphere", "cursor ai"],
        official_links={
            "home": "https://www.cursor.com",
            "pricing": "https://www.cursor.com/pricing",
            "docs": "https://docs.cursor.com",
        },
    ),
    "copilot": Competitor(
        name="copilot",
        aliases=["github copilot"],
        official_links={
            "home": "https://github.com/features/copilot",
            "docs": "https://docs.github.com/en/copilot",
            "pricing": "https://github.com/pricing",
        },
    ),
    "codex": Competitor(
        name="codex",
        aliases=["openai codex"],
        official_links={
            "home": "https://openai.com/index/introducing-codex/",
        },
    ),
    "windsurf": Competitor(
        name="windsurf",
        aliases=["windsurf ai", "codeium"],
        official_links={
            "home": "https://windsurf.com",
            "pricing": "https://windsurf.com/pricing",
        },
    ),
    "aider": Competitor(
        name="aider",
        aliases=["aider ai"],
        official_links={
            "home": "https://aider.chat",
            "docs": "https://aider.chat/docs/",
        },
    ),
    "gemini-cli": Competitor(
        name="gemini-cli",
        aliases=["gemini cli"],
        official_links={
            "home": "https://github.com/google-gemini/gemini-cli",
        },
    ),
    "opencode": Competitor(
        name="opencode",
        aliases=[],
        official_links={
            "home": "https://opencode.ai",
        },
    ),
}


def canonicalize(name: str) -> str:
    """去掉空格/连字符差异，做归一化匹配"""
    return name.strip().lower().replace(" ", "-")


# 对比任务连接词（M5.4：对比拆分）
_COMPARE_CONNECTORS = (" 和 ", " 与 ", " vs ", " vs. ", " and ", "、")
# 对比任务触发词
_COMPARE_MARKERS = ("对比分析", "对比", "比较", "compare", "vs")


def split_compare_text(task: str) -> list[str] | None:
    """尝试把 '对比 A 和 B' 拆成两个竞品文本；非对比任务返回 None。"""
    lowered = task.lower()
    if not any(m in lowered for m in _COMPARE_MARKERS):
        return None
    # 去掉对比前缀，得到 ' A 和 B' 剩余部分（若无前缀则保留原文，如 "Cursor vs Windsurf"）
    rest = task
    stripped = task.lstrip()
    for marker in _COMPARE_MARKERS:
        if stripped.lower().startswith(marker):
            rest = stripped[len(marker):]
            break
    for connector in _COMPARE_CONNECTORS:
        if connector in rest:
            parts = [p.strip() for p in rest.split(connector)]
            parts = [p for p in parts if p]
            if len(parts) >= 2:
                return parts[:2]
    return None


def resolve_competitors(task: str) -> list[Competitor]:
    """解析任务中的竞品（对比任务返回 2 个，普通任务返回 1 个）"""
    parts = split_compare_text(task)
    if parts:
        return [resolve_competitor(p) for p in parts]
    return [resolve_competitor(task)]


def resolve_competitor(name: str) -> Competitor:
    """把用户输入解析为 Competitor（优先命中注册表）。

    任务可能含中文前缀（如"分析 Claude Code"），因此先尝试在任务文本中
    匹配注册表内的规范名/别名子串；找不到时再退化为纯 ASCII 提取。
    """
    raw = name.strip()
    lowered = raw.lower()

    # 1) 子串匹配：任务文本含已知竞品名/别名
    for canon, competitor in COMPETITOR_REGISTRY.items():
        if canon in lowered or any(a in lowered for a in competitor.aliases):
            return competitor

    # 2) 精确匹配
    canon = canonicalize(raw)
    if canon in COMPETITOR_REGISTRY:
        return COMPETITOR_REGISTRY[canon]
    for competitor in COMPETITOR_REGISTRY.values():
        if canon in [canonicalize(a) for a in competitor.aliases]:
            return competitor

    # 3) 未知：提取 ASCII 部分作为规范名
    ascii_parts = "".join(c for c in raw if c.isascii() and (c.isalnum() or c.isspace()))
    fallback = canonicalize(ascii_parts) or "unknown"
    return Competitor(name=fallback)