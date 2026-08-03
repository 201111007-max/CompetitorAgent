"""数据源契约（架构文档命名入口，复用 collector.py 定义）"""
from __future__ import annotations

from competitor_agent.interfaces.collector import (
    ICompetitorDataCollector,
    ICompetitorDataSource,
)

__all__ = ["ICompetitorDataCollector", "ICompetitorDataSource"]
