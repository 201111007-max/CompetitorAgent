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
        external_refs={"github_repo": "anthropics/claude-code"},
    ),
    "cursor": Competitor(
        name="cursor",
        aliases=["anysphere", "cursor ai"],
        official_links={
            "home": "https://www.cursor.com",
            "pricing": "https://www.cursor.com/pricing",
            "docs": "https://docs.cursor.com",
        },
        external_refs={
            "github_repo": "getcursor/cursor",
            "marketplace": "https://marketplace.visualstudio.com/items?itemName=Anysphere.cursor",
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
        external_refs={"github_repo": "openai/codex"},
    ),
    "windsurf": Competitor(
        name="windsurf",
        aliases=["windsurf ai", "codeium"],
        official_links={
            "home": "https://windsurf.com",
            "pricing": "https://windsurf.com/pricing",
        },
        external_refs={
            "marketplace": "https://marketplace.visualstudio.com/items?itemName=Windsurf.windsurf",
        },
    ),
    "aider": Competitor(
        name="aider",
        aliases=["aider ai"],
        official_links={
            "home": "https://aider.chat",
            "docs": "https://aider.chat/docs/",
        },
        external_refs={"github_repo": "Aider-AI/aider"},
    ),
    "gemini-cli": Competitor(
        name="gemini-cli",
        aliases=["gemini cli"],
        official_links={
            "home": "https://github.com/google-gemini/gemini-cli",
        },
        external_refs={"github_repo": "google-gemini/gemini-cli"},
    ),
    "opencode": Competitor(
        name="opencode",
        aliases=[],
        official_links={
            "home": "https://opencode.ai",
        },
        external_refs={"github_repo": "sst/opencode"},
    ),
}


def canonicalize(name: str) -> str:
    """去掉空格/连字符差异，做归一化匹配"""
    return name.strip().lower().replace(" ", "-")


def resolve_competitor(name: str) -> Competitor:
    """把用户输入解析为 Competitor（注册表名称规范化映射，设计文档 47）。

    只做"名称 → 注册表条目"的映射（子串 + 精确 + 别名归一化）；
    未命中抛 ValueError——竞品识别已交给 LLM 结构化输出，不再用
    ASCII 抽取/对比拆分启发式造竞品。
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

    raise ValueError(f"注册表未收录竞品: {name!r}（请由 LLM 输出规范名，或先 discover 发现）")