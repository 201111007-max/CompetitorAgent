"""事件类型定义"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProgressEvent:
    """分析进度事件

    Attributes:
        event: 事件类型（phase_start / phase_complete / progress / report / error）
        phase: 当前阶段名称（strategic / tactical.<field> / report）
        progress: 整体进度 0.0-1.0
        message: 人类可读描述
        payload: 额外负载（缺口状态、置信度等）
    """

    event: str
    phase: str | None = None
    progress: float = 0.0
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "event": self.event,
            "phase": self.phase,
            "progress": self.progress,
            "message": self.message,
            "payload": self.payload,
        }

    def to_sse(self) -> str:
        """转换为 SSE 格式字符串（`data: {...}\\n\\n`）"""
        return f"data: {json.dumps(self.to_dict(), ensure_ascii=False)}\n\n"
