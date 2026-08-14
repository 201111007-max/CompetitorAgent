"""报告数据模型定义"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.domain_types.freshness import ReportFreshness
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import SourceEvidence


@dataclass
class DimensionResult:
    """单维度分析结论"""

    dimension: str
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    evidence: list[SourceEvidence] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: ResultStatus = ResultStatus.PARTIAL
    conflict_evidence: list[str] = field(default_factory=list)  # 仲裁丢弃的其他来源（设计文档 33）


@dataclass
class CompetitorReport:
    """单竞品分析报告"""

    competitor: Competitor
    dimension_results: list[DimensionResult] = field(default_factory=list)
    overall_score: float = 0.0
    overall_confidence: float = 0.0
    gaps_pending: list[InfoGap] = field(default_factory=list)
    markdown_report: str = ""
    terminal_state: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    freshness: ReportFreshness | None = None  # 新鲜度元数据（设计文档 26）


@dataclass
class CancelledResult(CompetitorReport):
    """分析被取消时返回的部分结果（已完成缺口 + 取消状态，而非静默丢弃）"""

    cancelled: bool = True


@dataclass
class ComparisonReport:
    """多竞品对比报告"""

    competitors: list[Competitor] = field(default_factory=list)
    reports: list[CompetitorReport] = field(default_factory=list)
    markdown_report: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())