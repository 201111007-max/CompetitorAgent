"""竞品注册表：预注册竞品随激活 DomainPack 提供（设计文档 79 §2.2 L2），未知竞品走通用采集

- ``COMPETITOR_REGISTRY`` 由激活 pack 的 ``registry_seeds`` 构建（category = pack.category_label）；
  yaml 缺失/损坏 → 回退内联 coding 默认（``_FALLBACK_REGISTRY``，与下沉前逐位一致）。
- ``reload_registry_from_pack`` / ``use_domain_pack`` 支持运行时切换（测试/多领域）。
- ``canonicalize/resolve_competitor`` 语义不变（doc 47）。
"""
from __future__ import annotations

from typing import Any

from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.observability.logger import get_logger

logger = get_logger("core.competitor_registry")


def _fallback_registry() -> dict[str, Competitor]:
    """内联 coding 默认（pack yaml 缺失时的兜底；与下沉前字面量逐位一致）。"""
    return {
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
        # ── 国内竞品（设计文档 83 §3，2026-09-08 web 核实回填）──────────────
        "trae": Competitor(
            name="trae",
            aliases=["trae-ai", "trae ide"],
            official_links={
                "home": "https://www.trae.ai",
                "pricing": "https://www.trae.ai/pricing",
            },
        ),
        "workbuddy": Competitor(
            name="workbuddy",
            aliases=["tencent workbuddy", "work-buddy"],
            official_links={
                "home": "https://www.workbuddy.ai",
                "docs": "https://www.codebuddy.cn/docs/workbuddy/Overview",
            },
        ),
        "zcode": Competitor(
            name="zcode",
            aliases=["z-code", "zcode agent", "智谱 z code"],
            official_links={
                # 用户更正确认（2026-09-08）：独立产品页，非 z.ai 主站；检索限定词 zcode.z.ai
                "home": "https://zcode.z.ai/cn",
                "pricing": "https://docs.bigmodel.cn/cn/coding-plan/overview",
            },
        ),
        "kimi-kcode": Competitor(
            name="kimi-kcode",
            aliases=["kimi kcode", "kimi code", "kimi k3 coding"],
            official_links={
                "home": "https://www.kimi.com",
                "docs": "https://platform.kimi.com/docs/guide",
            },
        ),
        "deepseek-harness": Competitor(
            name="deepseek-harness",
            aliases=["deepseek harness"],
            official_links={
                "home": "https://www.deepseek.com/harness",
            },
        ),
    }


def _registry_from_pack(pack: Any) -> dict[str, Competitor]:
    """pack.registry_seeds → Competitor 条目（category = pack.category_label）。"""
    label = str(getattr(pack, "category_label", "") or "")
    out: dict[str, Competitor] = {}
    for seed in getattr(pack, "registry_seeds", ()):
        out[seed.name] = Competitor(
            name=seed.name,
            aliases=list(seed.aliases),
            official_links=dict(seed.official_links),
            external_refs=dict(seed.external_refs),
            category=label,
        )
    return out


def _initial_registry() -> dict[str, Competitor]:
    try:
        from competitor_agent.core.domain_pack import active_domain_pack

        built = _registry_from_pack(active_domain_pack())
        if built:
            return built
    except Exception:
        logger.warning("注册表构建回退内联 coding 默认", exc_info=True)
    return _fallback_registry()


COMPETITOR_REGISTRY: dict[str, Competitor] = _initial_registry()


def reload_registry_from_pack(pack: Any) -> None:
    """运行时按 pack 重建注册表（测试/多领域切换；canonicalize/resolve 语义不变）。"""
    global COMPETITOR_REGISTRY
    COMPETITOR_REGISTRY = _registry_from_pack(pack) or _fallback_registry()


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
