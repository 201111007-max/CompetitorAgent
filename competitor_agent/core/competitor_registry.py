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
}


def canonicalize(name: str) -> str:
    """去掉空格/连字符差异，做归一化匹配"""
    return name.strip().lower().replace(" ", "-")


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