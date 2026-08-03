"""枚举类型定义"""
from enum import Enum


class DimensionType(Enum):
    """分析维度"""
    FEATURE = "feature"
    PRICING = "pricing"
    PERFORMANCE = "performance"
    ECOSYSTEM = "ecosystem"
    SENTIMENT = "sentiment"
    ROADMAP = "roadmap"


class GapStatus(Enum):
    """信息缺口状态（中枢状态机）"""
    OPEN = "open"
    PARTIAL = "partial"
    CONFIRMED = "confirmed"
    CLOSED = "closed"
    BLOCKED = "blocked"


class ResultStatus(Enum):
    """维度结果状态"""
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class TerminalState(Enum):
    """分析终态"""
    SUCCESS = "success"
    PARTIAL = "partial"
    DEGRADED = "degraded"
    TERMINAL_ERROR = "terminal_error"


class NetworkState(Enum):
    """网络/采集状态"""
    OK = "ok"
    RETRYABLE = "retryable"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"


class ObservationStatus(Enum):
    """采集观察状态"""
    OK = "ok"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


class EventType(Enum):
    """进度事件类型（SSE 复用）"""
    PHASE_START = "phase_start"
    PHASE_COMPLETE = "phase_complete"
    PROGRESS = "progress"
    REPORT = "report"
    ERROR = "error"
