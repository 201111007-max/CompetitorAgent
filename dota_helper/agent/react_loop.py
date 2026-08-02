"""推理循环控制 — 迭代次数限制、边际递减检测、错误恢复、流式事件产出

循环流程：
    用户消息 → 构建系统提示词（含工具描述）
      → LLM 生成 Thought/Action 或 Final Answer
      → 若 Final Answer → yield final 事件，结束
      → 若 Action → ToolDispatcher 分发 → 获取 Observation
      → yield thought/action/observation 事件
      → 追加到上下文 → 重新调用 LLM
      → 循环直到 Final Answer 或预算耗尽

可靠性特性：
- 错误分类：RECOVERABLE 重试 / DEGRADABLE 跳过 / TERMINAL 终止 / UNKNOWN 降级
- 熔断器：连续失败工具自动暂停调用
- Checkpoint：每轮迭代持久化推理状态，支持进程重启恢复
"""
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from dota_helper.agent.error_classifier import ErrorCategory, ErrorClassifier
from dota_helper.agent.injection_guard import OutputGuard, PromptInjectionDetector
from dota_helper.agent.plugin import PluginRegistry
from dota_helper.agent.response_parser import ResponseParser, ReActStep, StepType
from dota_helper.agent.tool_dispatcher import ToolDispatcher
from dota_helper.agent.tool_registry import ToolRegistry
from dota_helper.agent.prompts.react_system import ReactSystemPrompt
from dota_helper.domain_types.enums import BudgetDecision
from dota_helper.engines.budget import IterationBudget
from dota_helper.interfaces.llm import ILLMClient
from dota_helper.mcp_client.types import MCPConnectionError
from dota_helper.observability.logger import get_logger

logger = get_logger("agent.react_loop")

# 重试参数
_LLM_MAX_RETRIES = 2
_LLM_RETRY_BASE_DELAY = 1.0  # 秒


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
        checkpoint_dir: Checkpoint 持久化目录（可选）
    """
    session_id: str = ""
    conversation_id: str = ""
    messages: List[Dict[str, str]] = field(default_factory=list)
    iteration: int = 0
    total_tokens: int = 0
    checkpoint_dir: Optional[str] = None

    @property
    def _checkpoint_path(self) -> Optional[Path]:
        """Checkpoint 文件路径

        Returns:
            Optional[Path]: 文件路径，checkpoint_dir 未设置时返回 None
        """
        if not self.checkpoint_dir or not self.session_id:
            return None
        return Path(self.checkpoint_dir) / f"{self.session_id}_checkpoint.json"

    def save_checkpoint(self) -> None:
        """保存当前推理状态到 checkpoint 文件"""
        path = self._checkpoint_path
        if path is None:
            return

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "session_id": self.session_id,
                "conversation_id": self.conversation_id,
                "iteration": self.iteration,
                "total_tokens": self.total_tokens,
                "messages": self.messages,
                "saved_at": time.time(),
            }
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.debug("Checkpoint 已保存: session=%s, iteration=%d", self.session_id, self.iteration)
        except Exception as e:
            logger.warning("Checkpoint 保存失败: %s", str(e))

    def load_checkpoint(self) -> bool:
        """从 checkpoint 恢复推理状态

        Returns:
            bool: 是否成功恢复
        """
        path = self._checkpoint_path
        if path is None or not path.exists():
            return False

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.session_id = data.get("session_id", self.session_id)
            self.conversation_id = data.get("conversation_id", self.conversation_id)
            self.iteration = data.get("iteration", 0)
            self.total_tokens = data.get("total_tokens", 0)
            self.messages = data.get("messages", self.messages)
            logger.info(
                "Checkpoint 已恢复: session=%s, iteration=%d, messages=%d",
                self.session_id, self.iteration, len(self.messages),
            )
            return True
        except Exception as e:
            logger.warning("Checkpoint 恢复失败: %s", str(e))
            return False

    def clear_checkpoint(self) -> None:
        """清理 checkpoint 文件"""
        path = self._checkpoint_path
        if path is not None and path.exists():
            try:
                path.unlink()
                logger.debug("Checkpoint 已清理: session=%s", self.session_id)
            except Exception as e:
                logger.warning("Checkpoint 清理失败: %s", str(e))


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
        error_classifier: Optional[ErrorClassifier] = None,
        plugin_registry: Optional[PluginRegistry] = None,
        tool_registry: Optional[ToolRegistry] = None,
        injection_detector: Optional[PromptInjectionDetector] = None,
        output_guard: Optional[OutputGuard] = None,
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
        self._error_classifier = error_classifier or ErrorClassifier()
        self._plugin_registry = plugin_registry or PluginRegistry()
        self._tool_registry = tool_registry or ToolRegistry()
        self._injection_detector = injection_detector
        self._output_guard = output_guard
        if self._injection_detector is not None:
            logger.info("提示注入防御已启用（输入净化 + Observation 封装）")
        else:
            logger.info("提示注入防御未启用")
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
        2. 尝试从 checkpoint 恢复推理状态
        3. 迭代调用 LLM 获取 Thought/Action/Final Answer
        4. Action → ToolDispatcher 分发 → Observation
        5. 错误分类与恢复（重试/跳过/降级/终止）
        6. 预算控制检测是否继续
        7. 每轮迭代保存 checkpoint

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

        # 净化用户输入（提示注入第一层防御）
        sanitized_message = initial_message
        if self._injection_detector is not None:
            sanitized_message = self._injection_detector.sanitize_user_input(initial_message)

        # 初始化消息列表（优先从 checkpoint 恢复）
        if not context.messages:
            restored = context.load_checkpoint()
            if not restored:
                context.messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": sanitized_message},
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

        # 如果从 checkpoint 恢复，通知前端
        if context.iteration > 0:
            yield {
                "type": "progress",
                "session_id": context.session_id,
                "conversation_id": context.conversation_id,
                "iteration": context.iteration,
                "max_iterations": self._max_iterations,
                "progress": context.iteration / self._max_iterations,
                "restored": True,
            }

        # ── 插件：on_start ──
        await self._plugin_registry.dispatch_on_start({
            "session_id": context.session_id,
            "conversation_id": context.conversation_id,
            "messages": context.messages,
            "iteration": context.iteration,
        })

        # 迭代推理循环
        while True:
            context.iteration += 1
            iteration_delta = 0

            try:
                # ── 插件：before_llm_call ──
                context.messages = await self._plugin_registry.dispatch_before_llm_call(
                    context.messages
                )

                # ── 调用 LLM（带重试） ──
                llm_output = await self._call_llm_with_retry(context)

                # ── 插件：after_llm_call ──
                llm_output = await self._plugin_registry.dispatch_after_llm_call(llm_output)

                # ── 输出校验（提示注入第三层防御 + 敏感信息脱敏） ──
                if self._output_guard is not None:
                    check_result = self._output_guard.check(llm_output)
                    llm_output = check_result.cleaned
                    if check_result.is_empty:
                        # 空/占位符输出：重试一次，仍为空则降级为 Thought
                        logger.warning(
                            "LLM 输出为空或占位符，重试一次: iteration=%d",
                            context.iteration,
                        )
                        llm_output = await self._call_llm_with_retry(context)
                        check_result = self._output_guard.check(llm_output)
                        llm_output = check_result.cleaned

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

                    # 自动补全缺失的 match_id 参数
                    if not step.tool_args.get("match_id") and step.tool_name in (
                        "get_match_details", "get_match_items", "generate_review_report",
                        "analyze_ward_efficiency", "analyze_roshan_timing",
                        "analyze_late_game_decisions", "compare_match_performance",
                    ):
                        match_id = self._extract_match_id(context, step.thought)
                        if match_id:
                            step.tool_args["match_id"] = match_id

                    # ── 插件：before_action ──
                    plugin_args = await self._plugin_registry.dispatch_before_action(
                        step.tool_name, step.tool_args
                    )
                    if plugin_args is None:
                        # 插件阻止了工具调用
                        observation = f"⚠️ 工具 {step.tool_name} 已被插件阻止"
                    else:
                        step.tool_args = plugin_args

                    # 分发工具调用（含熔断检查和自动重试）
                    try:
                        observation = await self._tool_dispatcher.dispatch(
                            tool_name=step.tool_name,
                            args=step.tool_args,
                        )
                        # ── 插件：after_action ──
                        observation = await self._plugin_registry.dispatch_after_action(
                            step.tool_name, step.tool_args, observation
                        )
                    except Exception as tool_error:
                        # ── 插件：on_error ──
                        await self._plugin_registry.dispatch_on_error(
                            tool_error, context=f"tool:{step.tool_name}"
                        )

                        # 工具调用失败 → 分类处理
                        classified = self._error_classifier.classify(
                            tool_error, context=step.tool_name
                        )

                        if classified.category == ErrorCategory.RECOVERABLE:
                            # 可恢复错误（已在 dispatch 内重试过，仍失败）
                            observation = f"⚠️ 工具 {step.tool_name} 调用失败（已重试）: {classified.message}"
                        elif classified.category == ErrorCategory.DEGRADABLE:
                            # 可降级错误：跳过当前 Action，继续循环
                            observation = f"⚠️ 工具 {step.tool_name} 不可用: {classified.message}"
                        elif classified.category == ErrorCategory.TERMINAL:
                            # 致命错误：终止
                            yield {
                                "type": "error",
                                "session_id": context.session_id,
                                "conversation_id": context.conversation_id,
                                "content": f"致命错误: {classified.message}",
                            }
                            break
                        else:
                            # 未知错误：降级为 Observation
                            observation = f"⚠️ 工具 {step.tool_name} 调用异常: {classified.message}"

                        logger.warning(
                            "工具调用异常已处理: tool=%s, category=%s, detail=%s",
                            step.tool_name, classified.category.value, classified.detail,
                        )

                    # yield observation 事件
                    yield {
                        "type": "observation",
                        "session_id": context.session_id,
                        "conversation_id": context.conversation_id,
                        "content": observation,
                    }

                    # generate_review_report 返回完整报告后自动终止
                    if step.tool_name == "generate_review_report":
                        yield {
                            "type": "final",
                            "session_id": context.session_id,
                            "conversation_id": context.conversation_id,
                            "content": observation,
                        }
                        break

                    # 追加到上下文
                    context.messages.append(
                        {"role": "assistant", "content": llm_output}
                    )
                    # 工具结果封装为 <observation> 数据块（防 Observation 间接注入）
                    if self._injection_detector is not None:
                        observation = self._injection_detector.wrap_tool_result(observation)
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
                # ── 错误分类与恢复 ──
                classified = self._error_classifier.classify(e)

                if classified.category == ErrorCategory.RECOVERABLE:
                    # 可恢复错误（LLM 重试已耗尽）
                    logger.warning(
                        "LLM 调用失败（重试耗尽）: iteration=%d, error=%s",
                        context.iteration, classified.detail,
                    )
                    yield {
                        "type": "error",
                        "session_id": context.session_id,
                        "conversation_id": context.conversation_id,
                        "content": f"LLM 服务暂时不可用: {classified.message}",
                    }
                    break

                elif classified.category == ErrorCategory.DEGRADABLE:
                    # 可降级错误：跳过本轮，继续循环
                    logger.warning(
                        "降级跳过本轮: iteration=%d, error=%s",
                        context.iteration, classified.detail,
                    )
                    yield {
                        "type": "thought",
                        "session_id": context.session_id,
                        "conversation_id": context.conversation_id,
                        "content": f"[系统] {classified.message}，继续推理...",
                    }
                    continue

                elif classified.category == ErrorCategory.TERMINAL:
                    # 致命错误：终止
                    logger.error(
                        "致命错误终止: iteration=%d, error=%s",
                        context.iteration, classified.detail,
                    )
                    yield {
                        "type": "error",
                        "session_id": context.session_id,
                        "conversation_id": context.conversation_id,
                        "content": f"推理终止: {classified.message}",
                    }
                    break

                else:
                    # 未知错误：降级为纯 Thought 继续
                    logger.warning(
                        "未知错误降级: iteration=%d, error=%s",
                        context.iteration, classified.detail,
                    )
                    yield {
                        "type": "thought",
                        "session_id": context.session_id,
                        "conversation_id": context.conversation_id,
                        "content": f"[系统] {classified.message}，尝试继续推理...",
                    }
                    continue

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

            # 每轮迭代后保存 checkpoint
            context.save_checkpoint()

        # ── 插件：on_end ──
        await self._plugin_registry.dispatch_on_end({
            "session_id": context.session_id,
            "conversation_id": context.conversation_id,
            "messages": context.messages,
            "iteration": context.iteration,
        })

    async def _call_llm_with_retry(self, context: ReActContext) -> str:
        """调用 LLM，带自动重试

        对可恢复错误（超时、限流）进行最多 _LLM_MAX_RETRIES 次重试，
        指数退避。其他错误直接抛出。

        Args:
            context: 推理上下文

        Returns:
            str: LLM 输出文本

        Raises:
            Exception: 重试耗尽后仍失败，抛出最后一次异常
        """
        last_error: Optional[Exception] = None
        for attempt in range(1, _LLM_MAX_RETRIES + 1):
            try:
                return await self._llm_client.chat(
                    messages=context.messages,
                )
            except Exception as e:
                last_error = e
                classified = self._error_classifier.classify(e)
                if classified.category == ErrorCategory.RECOVERABLE and attempt < _LLM_MAX_RETRIES:
                    delay = _LLM_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "LLM 调用重试 %d/%d: delay=%.1fs, error=%s",
                        attempt, _LLM_MAX_RETRIES, delay, classified.detail,
                    )
                    await asyncio.sleep(delay)
                    continue
                # 不可恢复错误或重试耗尽
                raise last_error  # type: ignore[misc]

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

    @staticmethod
    def _extract_match_id(context: "ReActContext", thought: str) -> Optional[int]:
        """从用户消息或 Thought 中提取 match_id

        Args:
            context: ReAct 上下文
            thought: LLM 的 Thought 文本

        Returns:
            Optional[int]: 提取到的 match_id，未找到返回 None
        """
        # 1. 从 Thought 中提取
        match = re.search(r"(\d{10})", thought)
        if match:
            return int(match.group(1))

        # 2. 从用户消息中提取
        for msg in reversed(context.messages):
            if msg["role"] == "user":
                match = re.search(r"(\d{10})", msg["content"])
                if match:
                    return int(match.group(1))

        return None
