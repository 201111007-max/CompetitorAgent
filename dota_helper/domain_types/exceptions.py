"""P1-4: 复盘领域异常层次结构

提供统一的错误分类体系，区分可恢复 vs 不可恢复错误。
"""
from typing import List, Optional


class ReviewError(Exception):
    """复盘基础异常"""
    pass


class DataFetchError(ReviewError):
    """数据获取失败 — 可恢复（重试/缓存降级）"""

    def __init__(self, message: str, retryable: bool = True) -> None:
        self.retryable = retryable
        super().__init__(message)


class LLMError(ReviewError):
    """LLM 调用失败 — 可恢复（规则降级）"""

    def __init__(self, message: str, retryable: bool = True) -> None:
        self.retryable = retryable
        super().__init__(message)


class BudgetExhaustedError(ReviewError):
    """预算耗尽 — 不可恢复（生成部分报告）"""
    pass


class VerificationBlockedError(ReviewError):
    """验证阻止 — 可恢复（补充分析）"""

    def __init__(
        self,
        message: str,
        blocking_reasons: Optional[List[str]] = None,
        suggestions: Optional[List[str]] = None,
    ) -> None:
        self.blocking_reasons = blocking_reasons or []
        self.suggestions = suggestions or []
        super().__init__(message)


class SkillDefinitionError(ReviewError):
    """技能定义无效 — 可恢复（跳过该技能）"""

    def __init__(self, message: str, skill_name: str = "") -> None:
        self.skill_name = skill_name
        super().__init__(message)
