"""ReActLoop — 带预算与事件流式产出的推理循环控制

与 ReactAgent 的关系：ReactAgent 是"单轮 LLM 对话工具"；
ReactLoop 负责跨轮次的预算控制、错误处理与 ProgressEvent 产出，
供 facade API / Web SSE 消费。
"""
from __future__ import annotations

from typing import Callable

from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.react_loop")


class ReactLoop:
    """包装 ReactAgent 的循环控制器（同步，M1 版）"""

    def __init__(
        self,
        agent: ReactAgent,
        max_steps: int = 6,
        event_sink: Callable[[ProgressEvent], None] | None = None,
    ) -> None:
        self._agent = agent
        self._max_steps = max_steps
        self._event_sink = event_sink

    def run(self, task: str) -> str:
        """运行一次分析会话，返回最终结论文本。"""
        system_prompt = self._agent.build_system_prompt()
        self._emit(ProgressEvent(event="phase_start", phase="react", message="开始 ReAct 推理"))

        try:
            answer = self._agent.run(system_prompt, task, max_steps=self._max_steps)
        except LLMUnavailableError as exc:
            logger.warning("LLM 不可用，ReAct 无法执行: %s", exc)
            answer = "LLM 服务不可用，跳过 ReAct 推理。"
            self._emit(ProgressEvent(event="error", phase="react", message=str(exc)))

        self._emit(ProgressEvent(event="phase_complete", phase="react", message="ReAct 推理完成"))
        return answer

    def _emit(self, event: ProgressEvent) -> None:
        if self._event_sink is not None:
            self._event_sink(event)