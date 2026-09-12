"""设计文档 83 §3：国内竞品注册表扩充（工单 12）——TDD 先行。

核实结论（2026-09-08）：trae / workbuddy / zcode / kimi-kcode / deepseek-harness
五个国内竞品条目须可被 ``resolve_competitor`` 解析，且 official_links 带核实过的官网。
"""

from competitor_agent.core.competitor_registry import (
    COMPETITOR_REGISTRY,
    canonicalize,
    resolve_competitor,
)

# (规范名, 主页, 至少一个可命中的别名)
DOMESTIC_ENTRIES: list[tuple[str, str, str]] = [
    ("trae", "https://www.trae.ai", "trae-ai"),
    ("workbuddy", "https://www.workbuddy.ai", "tencent workbuddy"),
    ("zcode", "https://zcode.z.ai/cn", "zcode agent"),
    ("kimi-kcode", "https://www.kimi.com", "kimi code"),
    ("deepseek-harness", "https://www.deepseek.com/harness", "deepseek harness"),
]


class TestDomesticRegistryEntries:
    """注册表 5 个国内条目：解析 / 别名 / 官网链接（doc 83 §3）。"""

    def test_all_domestic_entries_registered(self) -> None:
        for canon, _home, _alias in DOMESTIC_ENTRIES:
            assert canon in COMPETITOR_REGISTRY, f"注册表缺少条目: {canon}"

    def test_resolve_by_canonical_name(self) -> None:
        for canon, _home, _alias in DOMESTIC_ENTRIES:
            resolved = resolve_competitor(canon)
            assert resolved.name == canon

    def test_resolve_by_alias(self) -> None:
        for canon, _home, alias in DOMESTIC_ENTRIES:
            resolved = resolve_competitor(alias)
            assert resolved.name == canon, f"别名 {alias!r} 未命中 {canon}"

    def test_official_home_links_verified(self) -> None:
        """主页链接来自 doc 83 §3 核实表；zcode 主页 = zcode.z.ai/cn（用户更正确认）。"""
        for canon, home, _alias in DOMESTIC_ENTRIES:
            links = COMPETITOR_REGISTRY[canon].official_links
            assert links.get("home") == home, f"{canon} home 链接与核实结论不符"

    def test_zcode_home_is_dedicated_site(self) -> None:
        """用户更正：Z Code 独立产品页 https://zcode.z.ai/cn（非 z.ai 主站）。"""
        assert COMPETITOR_REGISTRY["zcode"].official_links["home"] == "https://zcode.z.ai/cn"

    def test_category_still_ai_coding_agent(self) -> None:
        """doc 79 之前，category 默认值不动（保持现状等价）。"""
        for canon, _home, _alias in DOMESTIC_ENTRIES:
            assert COMPETITOR_REGISTRY[canon].category == "ai_coding_agent"

    def test_existing_registry_entries_untouched(self) -> None:
        """既有 8 个国际条目零变化（黄金回归）。"""
        for canon in ("claude-code", "cursor", "copilot", "codex", "windsurf", "aider", "gemini-cli", "opencode"):
            assert canon in COMPETITOR_REGISTRY

    def test_canonicalize_consistency(self) -> None:
        assert canonicalize("Kimi Kcode") == "kimi-kcode"
        assert canonicalize("DeepSeek Harness") == "deepseek-harness"
