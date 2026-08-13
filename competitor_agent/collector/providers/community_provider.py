"""CommunitySourceProvider — 社区口碑外部源（设计文档 23 §3.4）

HN / Reddit / X 等社区信号。依赖可用的搜索函数（如 MCP web_search / 搜索引擎 API）；
未注入搜索函数时 supports() 返回 False → 不产候选（正常降级到官网）。
"""
from __future__ import annotations

from typing import Callable

from competitor_agent.collector.source_selector import SourceCandidate
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation, SourceEvidence
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError

_TRUST = 0.6
# 社区搜索站点限定（HN / Reddit / X 等）
_SEARCH_SITES = "site:news.ycombinator.com OR site:reddit.com OR site:x.com"


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


class CommunitySourceProvider:
    """社区口碑源（sentiment 维度）：HN/Reddit/X 提及与信号（trust 0.6）"""

    kind = "social"
    name = "community"

    def __init__(self, search_fn: Callable[[str], str] | None = None) -> None:
        # 未注入搜索函数 → 无可用搜索后端 → 不产候选（避免默认路径触发真实网络）
        self._search = search_fn

    def supports(self, gap: InfoGap, competitor: Competitor) -> bool:
        return self._search is not None

    def candidates(self, gap: InfoGap, competitor: Competitor) -> list[SourceCandidate]:
        query = f"{competitor.name} {_SEARCH_SITES}"
        return [
            SourceCandidate(
                source_name="community_search",
                url=f"https://search/{competitor.name}",
                trust_level=_TRUST,
                kind="social",
            )
        ]

    def fetch(self, gap: InfoGap, candidate: SourceCandidate, competitor: Competitor) -> Observation:
        if self._search is None:
            raise DataSourceUnavailableError("未配置社区搜索后端")
        query = f"{competitor.name} {_SEARCH_SITES}"
        text = self._search(query)
        if text.startswith("⚠"):
            raise DataSourceUnavailableError(text)
        return _wrap_observation(gap, candidate, text)
