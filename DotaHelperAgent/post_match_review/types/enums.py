"""枚举类型定义"""
from enum import Enum


class BudgetDecision(Enum):
    """预算决策"""
    CONTINUE = "continue"
    STOP_BUDGET_USED = "stop_budget_used"
    STOP_TOKEN_LIMIT = "stop_token_limit"
    STOP_DIMINISHING = "stop_diminishing"
    REFUND = "refund"


class ReviewTerminalState(Enum):
    """复盘终态"""
    COMPLETED = "completed"
    MAX_ITERATIONS = "max_iterations"
    BUDGET_EXHAUSTED = "budget_exhausted"
    VERIFICATION_BLOCKED = "verification_blocked"
    INTERRUPTED = "interrupted"


class ReviewContinueState(Enum):
    """复盘继续态"""
    NEXT_PHASE = "next_phase"
    LOW_CONFIDENCE = "low_confidence"
    VERIFICATION_RETRY = "verification_retry"
    TOKEN_BUDGET_OK = "token_budget_ok"


class MatchType(Enum):
    """比赛类型"""
    NORMAL = "normal"
    STOMP = "stomp"
    COMEBACK = "comeback"
    QUICK_PUSH = "quick_push"
    CLOSE_GAME = "close_game"
