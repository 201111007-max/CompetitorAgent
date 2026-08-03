"""契约层：Protocol 定义与异常约定"""
from competitor_agent.interfaces.analyzer import ICompetitorAnalyzer
from competitor_agent.interfaces.collector import ICompetitorDataCollector, ICompetitorDataSource
from competitor_agent.interfaces.context import (
    AnalysisContext,
    AnalysisSession,
    BudgetState,
    ChatMessage,
    Skill,
    SourceContext,
    StopDecision,
)
from competitor_agent.interfaces.exceptions import (
    AnalysisNotApplicableError,
    BudgetExhaustedError,
    CompetitorAgentError,
    DataSourceUnavailableError,
    LLMUnavailableError,
    SourceBlockedError,
    TaskNotSupportedError,
)
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.interfaces.planner import IStrategicPlanner
from competitor_agent.interfaces.reporter import IReportBuilder
from competitor_agent.interfaces.verifier import IStopVerifier

__all__ = [
    "AnalysisContext",
    "AnalysisNotApplicableError",
    "AnalysisSession",
    "BudgetExhaustedError",
    "BudgetState",
    "ChatMessage",
    "CompetitorAgentError",
    "DataSourceUnavailableError",
    "ICompetitorAnalyzer",
    "ICompetitorDataCollector",
    "ICompetitorDataSource",
    "IFourLayerMemory",
    "IReportBuilder",
    "IStopVerifier",
    "IStrategicPlanner",
    "LLMUnavailableError",
    "Skill",
    "SourceBlockedError",
    "SourceContext",
    "StopDecision",
    "TaskNotSupportedError",
]