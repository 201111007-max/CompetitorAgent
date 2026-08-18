"""契约层：Protocol 定义与异常约定（planner/verifier/analyzer/collector 已删，设计文档 49）"""
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
from competitor_agent.interfaces.reporter import IReportBuilder

__all__ = [
    "AnalysisContext",
    "AnalysisNotApplicableError",
    "AnalysisSession",
    "BudgetExhaustedError",
    "BudgetState",
    "ChatMessage",
    "CompetitorAgentError",
    "DataSourceUnavailableError",
    "IFourLayerMemory",
    "IReportBuilder",
    "LLMUnavailableError",
    "Skill",
    "SourceBlockedError",
    "SourceContext",
    "StopDecision",
    "TaskNotSupportedError",
]
