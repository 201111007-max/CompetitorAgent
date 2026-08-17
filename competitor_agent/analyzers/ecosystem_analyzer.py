"""EcosystemAnalyzer — 生态能力维度分析器（设计文档 24 / 47）

多源聚合（GitHub / 插件市场 / 官方文档，经设计文档 23 路由）：
- mcp_servers：MCP server 支持（数量/第一方/第三方/发现途径）
- plugins：插件/扩展市场（数量、评分、关键插件）
- ide_support：IDE 支持（vscode/jetbrains/terminal）
- integrations：agentic tool-use / 外部工具集成
- repo_activity：仓库活跃度（stars/release 节奏/近 30 天 commit）

设计文档 47：仅 LLM 分析（无规则降级）。
"""
from __future__ import annotations

from typing import Any

from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted
from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.domain_types.enums import DimensionType
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation


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
