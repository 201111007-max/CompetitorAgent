"""采集数据源契约"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation
from competitor_agent.interfaces.context import SourceContext


@runtime_checkable
class ICompetitorDataSource(Protocol):
    """任一竞品信息数据源（官网/GitHub/定价页/评测/口碑）"""

    @property
    def source_name(self) -> str:
        """数据源标识（official_docs / pricing_page / github_api）"""
        ...

    def is_available(self) -> bool:
        """当前是否可用（供 SourceSelector 预筛）"""
        ...

    def fetch(self, gap: InfoGap, context: SourceContext) -> Observation:
        """按信息缺口抓取并返回观察结果。

        异常约定：
        - DataSourceUnavailableError: 源不可用，触发降级链
        - SourceBlockedError: 反爬/403，记录失败教训
        """
        ...


# 兼容别名（架构文档 data_source.py 命名）
ICompetitorDataCollector = ICompetitorDataSource

__all__ = ["ICompetitorDataCollector", "ICompetitorDataSource"]
