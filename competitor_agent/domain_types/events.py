"""事件类型定义"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


class StreamEvent:
    """流式对话事件名（设计文档 63 §3）：对话页前端据此归位气泡与增量。

    复用 ``ProgressEvent`` 的既有字段（event/phase/progress/message/payload），
    不新增字段：靠 ``event`` 取值区分，payload 上以 ``message_id`` 关联单条消息。
    """

    MESSAGE_START = "message.start"
    TEXT_DELTA = "text_delta"
    THINKING_DELTA = "thinking_delta"
    TEXT_STOP = "text.stop"
    MESSAGE_STOP = "message.stop"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    REPORT_SECTION = "report.section"


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
