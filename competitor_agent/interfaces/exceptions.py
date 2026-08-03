"""契约层异常约定"""
from __future__ import annotations


class CompetitorAgentError(Exception):
    """所有领域异常基类"""


class DataSourceUnavailableError(CompetitorAgentError):
    """数据源不可用（触发降级链）"""


class SourceBlockedError(CompetitorAgentError):
    """反爬/403，记录失败教训"""


class TaskNotSupportedError(CompetitorAgentError):
    """无法识别目标竞品，要求澄清"""


class AnalysisNotApplicableError(CompetitorAgentError):
    """Observation 与维度不匹配"""


class LLMUnavailableError(CompetitorAgentError):
    """LLM 不可用，降级到规则/缓存"""


class BudgetExhaustedError(CompetitorAgentError):
    """预算耗尽，进入终止流程"""
