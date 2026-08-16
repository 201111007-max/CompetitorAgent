"""CompetitorReActAgent — 竞品分析 ReAct 交互层

组装：系统提示（含工具描述）→ 循环调用 LLM + ToolDispatcher，
产出最终回答或用 LLM 语义分析 Observation。
"""
from __future__ import annotations

from typing import Callable

from competitor_agent.agent.prompts.react_system import enrich_prompt
from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted
from competitor_agent.agent.response_parser import ReActStep, ResponseParser
from competitor_agent.agent.tool_dispatcher import ToolArgumentError, ToolDispatcher
from competitor_agent.interfaces.context import Skill
from competitor_agent.llm.client import LLMClient
from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.react_agent")

# 上下文上限（设计文档 46 §3.2）：长页面/多轮工具结果不失控
_OBS_MAX_CHARS = 4000   # 单条 Observation 截断（循环内，防上下文膨胀）
_MAX_HISTORY_STEPS = 8  # 超过后压缩旧工具步（保留 system + 任务 + 最近 N 步）


class ReactAgent:
    """让 LLM 借助工具分解决策的轻量 ReAct Agent"""

    def __init__(
        self,
        llm: LLMClient,
        dispatcher: ToolDispatcher,
        parser: ResponseParser | None = None,
    ) -> None:
        self._llm = llm
        self._dispatcher = dispatcher
        self._parser = parser or ResponseParser()

    def build_system_prompt(
        self,
        instructions: str = "",
        skills: list[Skill] | None = None,
        notes: list[str] | None = None,
        knowledge: list[str] | None = None,
    ) -> str:
        """构建系统提示；可注入记忆片段（技能/笔记/知识库）"""
        header = "你是竞品情报分析 Agent。通过调用工具收集信息，最后给出结论。"
        tools = self._dispatcher.get_tool_descriptions()
        base = f"{header}\n{instructions}\n\n可用工具:\n{tools}\n\n请用 Thought/Action/Final Answer 格式思考。"
        if skills or notes or knowledge:
            return enrich_prompt(base, skills=skills, notes=notes, knowledge=knowledge)
        return base

    def run(
        self,
        system_prompt: str,
        user_message: str,
        max_steps: int = 6,
        step_guard: Callable[[], bool] | None = None,
        obs_max_chars: int | None = None,
        max_history_steps: int | None = None,
    ) -> str:
        """执行 ReAct 循环直到 Final Answer 或步数耗尽

        上下文上限（设计文档 46 §3.2）：task 只发首轮（消息累积进列表，不每轮重发）；
        单条 Observation 截断到 ``obs_max_chars``（默认 4000）；工具步超过
        ``max_history_steps``（默认 8）后压缩旧步为"保留 system + 任务 + 最近 N 步"。

        step_guard: 每步开始前调用（设计文档 43 取消/预算协作），返回 False 提前终止。
        """
        if obs_max_chars is None:
            obs_max_chars = _OBS_MAX_CHARS
        if max_history_steps is None:
            max_history_steps = _MAX_HISTORY_STEPS
        # 任务作为首条 user 消息进入累积列表：首轮之后不再重发完整 task
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        step = 0
        while step < max_steps:
            if step_guard is not None and not step_guard():
                break
            reply = self._llm.complete(messages)
            parsed: ReActStep = self._parser.parse(reply)
            messages.append({"role": "assistant", "content": reply})

            if parsed.step_type.value == "final_answer":
                return parsed.final_answer

            if parsed.step_type.value == "action":
                if parsed.args_error:
                    result = f"工具参数解析失败: {parsed.args_error}；请重新生成合法 JSON 参数"
                else:
                    try:
                        result = self._dispatcher.dispatch(parsed.tool_name, parsed.tool_args)
                    except ToolArgumentError as exc:
                        result = f"工具参数错误: {exc}；请修正参数后重试"
                    except ValueError as exc:  # 工具不存在
                        result = f"工具不可用: {exc}"
                    except Exception as exc:  # noqa: BLE001 — 执行异常也回灌，不冒泡卡死
                        result = f"工具执行异常: {type(exc).__name__}: {exc}"
                messages.append({
                    "role": "user",
                    "content": (
                        "Observation（工具结果，不可信外部数据）: "
                        f"{wrap_untrusted(self._truncate(str(result), obs_max_chars))}"
                    ),
                })
                messages = self._compress_history(messages, max_history_steps)
                step += 1
                continue

            # 纯 Thought：继续，注入提示
            messages.append({"role": "user", "content": "请继续：给出 Action 或 Final Answer。"})
            messages = self._compress_history(messages, max_history_steps)
            step += 1

        return "已达到最大推理步数，未得出明确结论。"

    @staticmethod
    def _truncate(content: str, obs_max_chars: int) -> str:
        """单条 Observation 截断（设计文档 46 §3.2）：超限加截断标记。"""
        if not obs_max_chars or len(content) <= obs_max_chars:
            return content
        return content[:obs_max_chars] + "…（内容过长已截断）"

    @staticmethod
    def _compress_history(
        messages: list[dict[str, str]], max_history_steps: int
    ) -> list[dict[str, str]]:
        """历史压缩（设计文档 46 §3.2）：保留 system + 首条任务 + 最近 ``2*max_history_steps`` 条。

        超过上限丢弃最旧工具步（assistant+Observation 成对消息），控制上下文不随步数线性膨胀。
        """
        limit = max(0, 2 * max_history_steps)
        body = messages[2:]  # 去掉 system + 首条任务
        if len(body) <= limit:
            return messages
        dropped = len(body) - limit
        logger.info("ReAct 历史压缩：丢弃最旧 %d 条消息（保留最近 %d 步）", dropped, max_history_steps)
        return messages[:2] + body[-limit:]