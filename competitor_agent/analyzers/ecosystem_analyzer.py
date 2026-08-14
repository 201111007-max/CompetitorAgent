"""EcosystemAnalyzer — 生态能力维度分析器（设计文档 24）

多源聚合（GitHub / 插件市场 / 官方文档，经设计文档 23 路由）：
- mcp_servers：MCP server 支持（数量/第一方/第三方/发现途径）
- plugins：插件/扩展市场（数量、评分、关键插件）
- ide_support：IDE 支持（vscode/jetbrains/terminal）
- integrations：agentic tool-use / 外部工具集成
- repo_activity：仓库活跃度（stars/release 节奏/近 30 天 commit）
"""
from __future__ import annotations

from typing import Any

from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted
from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.domain_types.enums import DimensionType
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation

# 规则降级：生态信号关键词（跨 github/marketplace/官方文档的通用信号）
_IDE_MARKERS = ("vscode", "jetbrains", "terminal", "ide", "visual studio")
_PLUGIN_MARKERS = ("rating", "download", "plugin", "extension", "marketplace")
_INTEGRATION_MARKERS = ("integration", "sdk", "api", "tool-use", "tool use", "agentic")
_MCP_MARKERS = ("mcp server", "mcp_server", "model context protocol", "mcp ")
_REPO_ACTIVITY_MARKERS = ("stars", "star:", "release", "commit", "forks")


class EcosystemAnalyzer(BaseCompetitorAnalyzer):
    """从 GitHub + 插件市场 + 文档集成章节盘点生态能力"""

    dimension = DimensionType.ECOSYSTEM

    def _build_prompt(self, observation: Observation, gap: InfoGap) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "你是竞品生态分析师。从给定文本（GitHub/插件市场/官方文档）盘点生态能力，"
                    "输出 JSON: {\"summary\": 一句话总结, "
                    "\"details\": {\"mcp_servers\": [{\"name\": ..., \"vendor\": ..., "
                    "\"discoverable_via\": ...}], \"plugins\": {\"count\": 数字或0, "
                    "\"rating\": 数字或0, \"top\": [\"...\"]}, "
                    "\"ide_support\": [\"vscode\", \"jetbrains\", \"terminal\"], "
                    "\"integrations\": [\"...\"], "
                    "\"repo_activity\": {\"stars\": 数字或0, \"last_release\": \"...\", "
                    "\"commits_30d\": 数字或0}}, "
                    "\"confidence\": 0-1}。数据缺失的字段给空/0，不要编造。"
                ),
            },
            {"role": "user", "content": wrap_untrusted(observation.raw_text[:4000], observation.evidence.url)},
        ]

    def _details_properties(self) -> dict[str, Any]:
        """details 结构（设计文档 34）：对齐评测 _ecosystem_signal 抽取键命名空间。"""
        return {
            "mcp_servers": {"type": "array", "items": {"type": "object"}},
            "plugins": {"type": "object"},
            "ide_support": {"type": "array", "items": {"type": "string"}},
            "integrations": {"type": "array", "items": {"type": "string"}},
            "repo_activity": {"type": "object"},
        }

    def _rule_extract(self, observation: Observation) -> dict[str, Any]:
        text = observation.raw_text or ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        low_lines = [ln.lower() for ln in lines]

        mcp_servers: list[dict[str, str]] = []
        plugins_top: list[str] = []
        ide_support: list[str] = []
        integrations: list[str] = []
        repo_activity: dict[str, Any] = {"stars": 0, "last_release": "", "commits_30d": 0}

        for idx, low in enumerate(low_lines):
            if any(m in low for m in _MCP_MARKERS) and len(lines[idx]) < 120:
                mcp_servers.append({"name": lines[idx][:80], "vendor": "", "discoverable_via": "文档/仓库"})
            if any(m in low for m in _PLUGIN_MARKERS) and len(lines[idx]) < 120:
                plugins_top.append(lines[idx][:80])
            if any(m in low for m in _IDE_MARKERS) and len(lines[idx]) < 80:
                ide = _first_ide(low)
                if ide and ide not in ide_support:
                    ide_support.append(ide)
            if any(m in low for m in _INTEGRATION_MARKERS) and len(lines[idx]) < 120:
                integrations.append(lines[idx][:80])
            # 仓库活跃度信号（GitHub provider 输出）
            if "stars:" in low:
                repo_activity["stars"] = _extract_int(lines[idx])
            if "release" in low or "版本" in lines[idx]:
                repo_activity["last_release"] = lines[idx][:80]
            if "commit" in low and ("最近" in lines[idx] or "近期" in lines[idx]):
                repo_activity["commits_30d"] = _extract_int(lines[idx])

        # 去重
        plugins_top = _dedupe(plugins_top)[:5]
        integrations = _dedupe(integrations)[:8]
        mcp_servers = _dedupe_dict(mcp_servers, "name")[:10]

        has_signal = bool(mcp_servers or plugins_top or ide_support or integrations or repo_activity["stars"])
        return {
            "summary": (
                f"生态盘点：MCP server {len(mcp_servers)} 个、插件 {len(plugins_top)} 条、"
                f"IDE {', '.join(ide_support) or '未知'}" if has_signal else "生态信号不足，未编造具体结论"
            ),
            "details": {
                "mcp_servers": mcp_servers,
                "plugins": {"count": len(plugins_top), "rating": 0, "top": plugins_top},
                "ide_support": ide_support,
                "integrations": integrations,
                "repo_activity": repo_activity,
            },
            "confidence": 0.7 if has_signal else 0.3,
        }


def _first_ide(low_line: str) -> str:
    for marker in ("vscode", "visual studio"):
        if marker in low_line:
            return "vscode"
    for marker in ("jetbrains",):
        if marker in low_line:
            return "jetbrains"
    if "terminal" in low_line:
        return "terminal"
    return ""


def _extract_int(line: str) -> int:
    digits = "".join(ch for ch in line if ch.isdigit())
    return int(digits) if digits else 0


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def _dedupe_dict(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        k = str(item.get(key, ""))
        if k and k not in seen:
            seen.add(k)
            out.append(item)
    return out
