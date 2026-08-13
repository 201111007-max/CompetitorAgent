"""MarketplaceSourceProvider — 插件市场外部源（设计文档 23 §3.4）

VS Code / JetBrains 插件市场：评分、下载量、插件数量。薄封装 MCP web_extract，
可注入 extract_fn（测试用 mock，不触发真实网络）。
"""
from __future__ import annotations

from typing import Callable

from competitor_agent.collector.source_selector import SourceCandidate
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation, SourceEvidence
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError

_MARKETPLACE_KEY = "marketplace"
_TRUST = 0.8


def _wrap_observation(gap: InfoGap, candidate: SourceCandidate, text: str) -> Observation:
    return Observation(
        gap_field=gap.field,
        source=candidate.source_name,
        raw_text=text,
        evidence=SourceEvidence(
            source_name=candidate.source_name,
            url=candidate.url,
            content_hash=SourceEvidence.compute_hash(text),
            trust_level=candidate.trust_level,
        ),
    )


class MarketplaceSourceProvider:
    """插件市场源（VS Code / JetBrains）：评分/下载量/插件数（trust 0.8）"""

    kind = "marketplace"
    name = "marketplace"

    def __init__(self, extract_fn: Callable[[str], str] | None = None) -> None:
        if extract_fn is None:
            from competitor_agent.mcp_server.tools.web_tools import web_extract  # 惰性导入

            extract_fn = web_extract
        self._extract = extract_fn

    def supports(self, gap: InfoGap, competitor: Competitor) -> bool:
        return bool(competitor.external_refs.get(_MARKETPLACE_KEY))

    def candidates(self, gap: InfoGap, competitor: Competitor) -> list[SourceCandidate]:
        url = competitor.external_refs[_MARKETPLACE_KEY]
        return [
            SourceCandidate(
                source_name="marketplace",
                url=url,
                trust_level=_TRUST,
                kind="marketplace",
            )
        ]

    def fetch(self, gap: InfoGap, candidate: SourceCandidate, competitor: Competitor) -> Observation:
        text = self._extract(candidate.url)
        if text.startswith("⚠"):
            raise DataSourceUnavailableError(text)
        return _wrap_observation(gap, candidate, text)
