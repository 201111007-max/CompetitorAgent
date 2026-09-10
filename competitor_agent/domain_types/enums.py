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


# 六维规范名（值同 DimensionType；顺序为 schema/prompt 嵌入的规范序）。
# 单一来源（设计文档 87 §1.4-C3）：react_schemas.DIMENSIONS 与 task_parser._VALID_DIMENSIONS
# 均由此派生，新增第 7 个维度只需改此处与 DimensionType。
DIMENSION_NAMES: list[str] = [
    "pricing",
    "feature",
    "performance",
    "ecosystem",
    "sentiment",
    "roadmap",
]


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
