"""推理循环控制 — 迭代次数限制、边际递减检测、错误恢复、流式事件产出

循环流程：
    用户消息 → 构建系统提示词（含工具描述）
      → LLM 生成 Thought/Action 或 Final Answer
      → 若 Final Answer → yield final 事件，结束
      → 若 Action → ToolDispatcher 分发 → 获取 Observation
      → yield thought/action/observation 事件
      → 追加到上下文 → 重新调用 LLM
      → 循环直到 Final Answer 或预算耗尽
"""
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

from dota_helper.agent.response_parser import ResponseParser, ReActStep, StepType
from dota_helper.agent.tool_dispatcher import ToolDispatcher
from dota_helper.agent.prompts.react_system import ReactSystemPrompt
from dota_helper.domain_types.enums import BudgetDecision
from dota_helper.engines.budget import IterationBudget
from dota_helper.interfaces.llm import ILLMClient
from dota_helper.observability.logger import get_logger

logger = get_logger("agent.react_loop")


@dataclass
class ReActContext:
    """ReAct 推理上下文

    承载整个推理循环过程中的状态，包括对话历史、会话信息等。

    Attributes:
        session_id: 会话 ID
        conversation_id: 对话 ID
        messages: OpenAI 风格消息列表（system + user + assistant 历史）
        iteration: 当前迭代次数
        total_tokens: 累计 Token 消耗
    """
    session_id: str = ""
    conversation_id: str = ""
    messages: List[Dict[str, str]] = field(default_factory=list)
    iteration: int = 0
    total_tokens: int = 0


class ReActLoop:
    """推理循环控制器

    管理完整的 Thought → Action → Observation 迭代循环，
    包含预算控制（迭代次数 + Token 消耗 + 边际递减检测）和错误恢复。

    Args:
        llm_client: LLM 客户端（ILLMClient 协议）
        tool_dispatcher: MCP 工具分发器
        parser: LLM 输出解析器
        prompt_builder: 系统提示词构建器
        max_iterations: 最大迭代次数（默认 15）
        max_tokens: 最大 Token 消耗（默认 40000）
        diminishing_threshold: 边际递减阈值（默认 500）
        diminishing_window: 边际递减检测窗口（默认 2）
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        tool_dispatcher: ToolDispatcher,
        parser: Optional[ResponseParser] = None,
        prompt_builder: Optional[ReactSystemPrompt] = None,
        max_iterations: int = 15,
        max_tokens: int = 40000,
        diminishing_threshold: int = 500,
        diminishing_window: int = 2,
    ) -> None:
        """初始化推理循环控制器"""
        self._llm_client = llm_client
        self._tool_dispatcher = tool_dispatcher
        self._parser = parser or ResponseParser()
        self._prompt_builder = prompt_builder or ReactSystemPrompt()
        self._max_iterations = max_iterations
        self._max_tokens = max_tokens
        self._diminishing_threshold = diminishing_threshold
        self._diminishing_window = diminishing_window

        logger.info(
            "ReAct 循环初始化: max_iterations=%d, max_tokens=%d, "
            "diminishing_threshold=%d, diminishing_window=%d",
            max_iterations, max_tokens, diminishing_threshold, diminishing_window,
        )

    async def execute(
        self,
        initial_message: str,
        context: ReActContext,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """执行推理循环，yield 事件流

        完整的 ReAct 循环实现：
        1. 构建系统提示词（含工具描述）
        2. 迭代调用 LLM 获取 Thought/Action/Final Answer
        3. Action → ToolDispatcher 分发 → Observation
        4. 预算控制检测是否继续
        5. 错误恢复与降级

        Args:
            initial_message: 用户输入消息
            context: 推理上下文（包含会话 ID、对话历史等）

        Yields:
            Dict[str, Any]: SSE 事件字典，包含 9 种事件类型
        """
        # 初始化预算控制器
        budget = IterationBudget(
            max_iterations=self._max_iterations,
            max_tokens=self._max_tokens,
            diminishing_threshold=self._diminishing_threshold,
            min_continuations=self._diminishing_window,
        )

        # 构建系统提示词
        tool_descriptions = self._tool_dispatcher.get_tool_descriptions()
        system_prompt = self._prompt_builder.build(tool_descriptions=tool_descriptions)

        # 初始化消息列表
        if not context.messages:
            context.messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": initial_message},
            ]

        # yield session 事件
        if not context.session_id:
            context.session_id = f"sess_{uuid.uuid4().hex[:12]}"
        if not context.conversation_id:
            context.conversation_id = f"conv_{uuid.uuid4().hex[:12]}"

        yield {
            "type": "session",
            "session_id": context.session_id,
            "conversation_id": context.conversation_id,
        }

        # 迭代推理循环
        while True:
            context.iteration += 1
            iteration_delta = 0

            try:
                # 调用 LLM
                llm_output = await self._llm_client.chat(
                    messages=context.messages,
                )

                # 解析 LLM 输出
                step = self._parser.parse(llm_output)

                if step.step_type == StepType.FINAL_ANSWER:
                    # 终止：yield final 事件
                    yield {
                        "type": "final",
                        "session_id": context.session_id,
                        "conversation_id": context.conversation_id,
                        "content": step.final_answer,
                    }
                    break

                elif step.step_type == StepType.THOUGHT:
                    # 纯 Thought：yield thought 事件
                    yield {
                        "type": "thought",
                        "session_id": context.session_id,
                        "conversation_id": context.conversation_id,
                        "content": step.thought,
                    }
                    # 追加到上下文并继续
                    context.messages.append(
                        {"role": "assistant", "content": llm_output}
                    )

                elif step.step_type == StepType.ACTION:
                    # Thought → Action → Observation
                    # yield thought 事件
                    if step.thought:
                        yield {
                            "type": "thought",
                            "session_id": context.session_id,
                            "conversation_id": context.conversation_id,
                            "content": step.thought,
                        }

                    # yield action 事件
                    yield {
                        "type": "action",
                        "session_id": context.session_id,
                        "conversation_id": context.conversation_id,
                        "content": f"调用工具 {step.tool_name}",
                        "input": {
                            "tool": step.tool_name,
                            **step.tool_args,
                        },
                    }

                    # 分发工具调用
                    observation = await self._tool_dispatcher.dispatch(
                        tool_name=step.tool_name,
                        args=step.tool_args,
                    )

                    # yield observation 事件
                    yield {
                        "type": "observation",
                        "session_id": context.session_id,
                        "conversation_id": context.conversation_id,
                        "content": observation,
                    }

                    # 追加到上下文
                    context.messages.append(
                        {"role": "assistant", "content": llm_output}
                    )
                    context.messages.append(
                        {"role": "user", "content": f"Observation: {observation}"}
                    )

                    # yield progress 事件
                    yield {
                        "type": "progress",
                        "session_id": context.session_id,
                        "conversation_id": context.conversation_id,
                        "iteration": context.iteration,
                        "max_iterations": self._max_iterations,
                        "progress": context.iteration / self._max_iterations,
                    }

            except Exception as e:
                # 错误恢复：yield error 事件并终止
                logger.error(
                    "推理循环异常 (iteration=%d): %s", context.iteration, str(e)
                )
                yield {
                    "type": "error",
                    "session_id": context.session_id,
                    "conversation_id": context.conversation_id,
                    "content": f"推理过程中发生错误：{str(e)}",
                }
                break

            # 预算控制
            decision = budget.consume(delta_tokens=iteration_delta)
            if decision != BudgetDecision.CONTINUE:
                logger.info(
                    "推理循环终止: decision=%s, iteration=%d, tokens=%d",
                    decision.value, context.iteration, context.total_tokens,
                )
                # 如果还没产出 final，生成一个总结性 final
                yield {
                    "type": "final",
                    "session_id": context.session_id,
                    "conversation_id": context.conversation_id,
                    "content": "推理预算耗尽，分析已达到当前条件下的最优结论。",
                }
                break

    def should_continue(self, iteration: int, token_delta: int) -> BudgetDecision:
        """判断是否继续迭代（预算控制 + 边际递减检测）

        Args:
            iteration: 当前迭代次数
            token_delta: 本轮 Token 增量

        Returns:
            BudgetDecision: 预算决策
        """
        if iteration >= self._max_iterations:
            return BudgetDecision.STOP_BUDGET_USED

        if token_delta < self._diminishing_threshold and iteration > self._diminishing_window:
            return BudgetDecision.STOP_DIMINISHING

        return BudgetDecision.CONTINUE
