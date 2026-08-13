"""数据源契约（架构文档命名入口，复用 collector.py 定义）

设计文档 23：新增 `ExternalSourceProvider` 协议——官网之外的外部源
（GitHub / 插件市场 / 社区 / 榜单）以可注入提供方接入 SourceSelector 多源路由。
"""
from __future__ import annotations

from typing import Protocol

from competitor_agent.collector.source_selector import SourceCandidate
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation
from competitor_agent.interfaces.collector import (
    ICompetitorDataCollector,
    ICompetitorDataSource,
)


class ExternalSourceProvider(Protocol):
    """外部源提供方：对缺口产出官网之外的候选源，并负责按候选抓取观测。

    - `candidates()` 生成候选（带 kind/trust_level），由 SourceSelector 排序后进入降级链；
    - `fetch()` 按候选源抓取并包装为 Observation；失败抛 DataSourceUnavailableError 走降级。
    """

    kind: str  # "github" / "marketplace" / "benchmark" / "social"
    name: str  # 如 "github_releases"

    def supports(self, gap: InfoGap, competitor: Competitor) -> bool:
        """该提供方对缺口/竞品是否有效（如竞品有 github_repo 才支持 github）"""
        ...

    def candidates(self, gap: InfoGap, competitor: Competitor) -> list[SourceCandidate]:
        """返回该提供方对缺口能产出的候选源（URL 或具名源）"""
        ...

    def fetch(self, gap: InfoGap, candidate: SourceCandidate, competitor: Competitor) -> Observation:
        """按候选源抓取观测；失败抛 DataSourceUnavailableError 走降级链。"""
        ...


# 兼容别名（架构文档 data_source.py 命名）
ICompetitorDataCollector = ICompetitorDataSource

__all__ = ["ExternalSourceProvider", "ICompetitorDataCollector", "ICompetitorDataSource"]
