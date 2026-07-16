"""事件类型定义"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class VerificationResult:
    """验证结果"""
    passed: bool
    blocking_reasons: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
