"""GithubSourceProvider — GitHub 外部源（设计文档 23 §3.4）

仓库活跃度 / Release 版本时间线 / commit 频率。薄封装 MCP github_tools，
函数可注入（测试用 mock，不触发真实网络）；失败返回 "⚠" 前缀消息 → 抛
DataSourceUnavailableError 走降级链。
"""
from __future__ import annotations

from typing import Callable

from competitor_agent.collector.source_selector import SourceCandidate
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation, SourceEvidence
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError

_REPO_KEY = "github_repo"
_TRUST = 0.85


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


class GithubSourceProvider:
    """GitHub 仓库源：stars / releases / commits（trust 0.85）"""

    kind = "github"
    name = "github"

    def __init__(
        self,
        stars_fn: Callable[[str], str] | None = None,
        releases_fn: Callable[[str, int], str] | None = None,
        commits_fn: Callable[[str, int], str] | None = None,
    ) -> None:
        from competitor_agent.mcp_server.tools.github_tools import (  # 惰性导入，避免加重 MCP 依赖
            github_commits,
            github_releases,
            github_stars,
        )

        self._stars = stars_fn or github_stars
        self._releases = releases_fn or github_releases
        self._commits = commits_fn or github_commits

    def supports(self, gap: InfoGap, competitor: Competitor) -> bool:
        return bool(competitor.external_refs.get(_REPO_KEY))

    def candidates(self, gap: InfoGap, competitor: Competitor) -> list[SourceCandidate]:
        repo = competitor.external_refs[_REPO_KEY]
        return [
            SourceCandidate(
                source_name="github_stars", url=f"https://github.com/{repo}", trust_level=_TRUST, kind="github"
            ),
            SourceCandidate(
                source_name="github_releases",
                url=f"https://github.com/{repo}/releases",
                trust_level=_TRUST,
                kind="github",
            ),
            SourceCandidate(
                source_name="github_commits",
                url=f"https://github.com/{repo}/commits",
                trust_level=_TRUST,
                kind="github",
            ),
        ]

    def fetch(self, gap: InfoGap, candidate: SourceCandidate, competitor: Competitor) -> Observation:
        repo = competitor.external_refs.get(_REPO_KEY, "")
        if not repo:
            raise DataSourceUnavailableError(f"竞品 {competitor.name} 无 github_repo 引用")
        if candidate.source_name == "github_stars":
            text = self._stars(repo)
        elif candidate.source_name == "github_releases":
            text = self._releases(repo, 5)
        elif candidate.source_name == "github_commits":
            text = self._commits(repo, 30)
        else:
            raise DataSourceUnavailableError(f"未知 github 源: {candidate.source_name}")
        if text.startswith("⚠"):
            raise DataSourceUnavailableError(text)
        return _wrap_observation(gap, candidate, text)
