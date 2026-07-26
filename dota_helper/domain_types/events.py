"""事件类型定义"""
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VerificationResult:
    """验证结果"""
    passed: bool
    blocking_reasons: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


@dataclass
class ProgressEvent:
    """复盘进度事件

    Attributes:
        event: 事件类型，可选值为
            phase_start / phase_complete / progress / report / error
        phase: 当前阶段名称（可选）
        progress: 整体进度，范围 0.0 - 1.0
        message: 人类可读的状态描述
        payload: 额外负载数据
    """

    event: str
    phase: Optional[str] = None
    progress: float = 0.0
    message: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "event": self.event,
            "phase": self.phase,
            "progress": self.progress,
            "message": self.message,
            "payload": self.payload,
        }

    def to_sse(self) -> str:
        """转换为 SSE 格式字符串

        Returns:
            str: 符合 `data: {...}\n\n` 格式的 SSE 事件行
        """
        return f"data: {json.dumps(self.to_dict(), ensure_ascii=False)}\n\n"
