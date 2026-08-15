"""ReActLoop — 带预算与事件流式产出的推理循环控制

与 ReactAgent 的关系：ReactAgent 是"单轮 LLM 对话工具"；
ReactLoop 负责跨轮次的预算控制、错误处理与 ProgressEvent 产出，
供 facade API / Web SSE 消费。

设计文档 43 §3.1：ReactLoop 统一会话上下文——与主流水线共享
取消（session_id）、预算（IterationBudget）、记忆/RAG 注入、事件（event_sink），
消除"ReAct 是旁路"的割裂。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.core.budget import IterationBudget
from competitor_agent.core.checkpoint import is_cancelled
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.react_loop")


@dataclass
class ReactRunResult:
    """ReAct 一次运行的完整结果（含共享上下文状态，设计文档 43）"""

    answer: str
    steps: int = 0
    cancelled: bool = False
    budget_exhausted: bool = False


class ReactLoop:
    """包装 ReactAgent 的循环控制器（同步，M1 版）

    Args:
        agent: ReactAgent 实例
        max_steps: 最大推理步数
        event_sink: 进度事件回调
        session_id: 会话 ID（共享取消标志，None 不协作）
        budget: 迭代预算（共享步数/成本，None 不限制）
        memory_context_fn: (task) -> 记忆召回文本（设计文档 35 的 recent_context，None 跳过）
        rag_fn: (task) -> 知识库检索文本（None 跳过）
    """

    def __init__(
        self,
        agent: ReactAgent,
        max_steps: int = 6,
        event_sink: Callable[[ProgressEvent], None] | None = None,
        session_id: str | None = None,
        budget: IterationBudget | None = None,
        memory_context_fn: Callable[[str], str] | None = None,
        rag_fn: Callable[[str], str] | None = None,
    ) -> None:
        self._agent = agent
        self._max_steps = max_steps
        self._event_sink = event_sink
        self._session_id = session_id
        self._budget = budget
        self._memory_context_fn = memory_context_fn
        self._rag_fn = rag_fn

    def run(self, task: str) -> str:
        """运行一次分析会话，返回最终结论文本（向后兼容：不携带取消/预算状态）。"""
        return self.run_with_result(task).answer

    def run_with_result(self, task: str) -> ReactRunResult:
        """带共享会话上下文运行：每步前取消/预算协作，记忆/RAG 注入系统提示。

        返回完整结果（结论文本 + 步数 + 取消/预算耗尽标志），供结构化产物消费。
        """
        system_prompt = self._agent.build_system_prompt(
            notes=self._memory_notes(task),
            knowledge=self._rag_knowledge(task),
        )
        self._emit(ProgressEvent(event="phase_start", phase="react", message="开始 ReAct 推理"))

        result = ReactRunResult(answer="")
        try:
            result.answer = self._agent.run(
                system_prompt,
                task,
                max_steps=self._max_steps,
                step_guard=self._step_guard(result),
            )
            # 取消/预算中断时 ReactAgent 返回"已达最大步数"，此处覆盖为准确终止文案
            if result.cancelled:
                result.answer = "推理已取消（会话被中断）。"
                self._emit(
                    ProgressEvent(event="cancelled", phase="react", message="ReAct 推理已取消")
                )
            elif result.budget_exhausted:
                result.answer = "推理已停止（预算耗尽）。"
                self._emit(
                    ProgressEvent(event="error", phase="react", message="ReAct 推理预算耗尽")
                )
        except LLMUnavailableError as exc:
            logger.warning("LLM 不可用，ReAct 无法执行: %s", exc)
            result.answer = "LLM 服务不可用，跳过 ReAct 推理。"
            self._emit(ProgressEvent(event="error", phase="react", message=str(exc)))
        self._emit(ProgressEvent(event="phase_complete", phase="react", message="ReAct 推理完成"))
        return result

    def _step_guard(self, result: ReactRunResult) -> Callable[[], bool] | None:
        """每步前置检查：先取消、后预算。返回 False 提前终止循环。"""
        if self._session_id is None and self._budget is None:
            return None

        def guard() -> bool:
            if self._session_id and is_cancelled(self._session_id):
                logger.info("会话 %s 已取消，中断 ReAct 循环", self._session_id)
                result.cancelled = True
                return False
            if self._budget is not None and not self._budget.consume(delta_cost=0.0):
                logger.warning("ReAct 预算耗尽，中断推理循环")
                result.budget_exhausted = True
                return False
            result.steps += 1
            return True

        return guard

    def _memory_notes(self, task: str) -> list[str] | None:
        """记忆召回（设计文档 35）：注入为系统提示的历史经验笔记；失败静默降级。"""
        if self._memory_context_fn is None:
            return None
        try:
            ctx = self._memory_context_fn(task)
        except Exception:  # noqa: BLE001 — 记忆召回失败不影响推理
            logger.warning("ReAct 记忆注入失败", exc_info=True)
            return None
        return [ctx] if ctx else None

    def _rag_knowledge(self, task: str) -> list[str] | None:
        """RAG 检索（设计文档 02/32）：注入为知识库参考片段；失败静默降级。"""
        if self._rag_fn is None:
            return None
        try:
            ctx = self._rag_fn(task)
        except Exception:  # noqa: BLE001 — 检索失败不影响推理
            logger.warning("ReAct RAG 注入失败", exc_info=True)
            return None
        return [ctx] if ctx else None

    def _emit(self, event: ProgressEvent) -> None:
        if self._event_sink is not None:
            self._event_sink(event)
