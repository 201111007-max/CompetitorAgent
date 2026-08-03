"""领域数据模型"""
from competitor_agent.domain_types.competitor import Competitor, CompetitorProfile
from competitor_agent.domain_types.enums import (
    DimensionType,
    EventType,
    GapStatus,
    NetworkState,
    ObservationStatus,
    ResultStatus,
    TerminalState,
)
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation, SourceEvidence
from competitor_agent.domain_types.report import ComparisonReport, CompetitorReport, DimensionResult
from competitor_agent.domain_types.strategy import CompetitorStrategy, DimensionBudget

__all__ = [
    "ComparisonReport",
    "Competitor",
    "CompetitorProfile",
    "CompetitorReport",
    "CompetitorStrategy",
    "DimensionBudget",
    "DimensionResult",
    "DimensionType",
    "EventType",
    "GapStatus",
    "InfoGap",
    "NetworkState",
    "Observation",
    "ObservationStatus",
    "ProgressEvent",
    "ResultStatus",
    "SourceEvidence",
    "TerminalState",
]