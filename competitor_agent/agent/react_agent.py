"""CompetitorReActAgent — 竞品分析 ReAct 交互层

组装：系统提示（含工具描述）→ 循环调用 LLM + ToolDispatcher，
产出最终回答或用 LLM 语义分析 Observation。
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from competitor_agent.agent.prompts.react_system import enrich_prompt
from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted
from competitor_agent.agent.response_parser import ReActStep, ResponseParser
from competitor_agent.agent.tool_dispatcher import ToolArgumentError, ToolDispatcher
from competitor_agent.interfaces.context import Skill
from competitor_agent.llm.client import LLMClient
from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.react_agent")

# 原生协议（设计文档 53）：工具经 tools 请求参数下发，无需在 system prompt 里写格式说明
_PROTOCOLS = ("native", "react")

# 上下文上限（设计文档 46 §3.2）：长页面/多轮工具结果不失控
_OBS_MAX_CHARS = 4000   # 单条 Observation 截断（循环内，防上下文膨胀）
_MAX_HISTORY_STEPS = 8  # 超过后把旧工具步折叠为摘要（保留 system + 任务 + 最近 N 步）
# 压缩摘要块自身上限：折叠是"一行一旧步"，行数与总字符都要封顶，防摘要块反向膨胀
_SUMMARY_MAX_LINES = 6    # 最多保留最近折叠行数
_SUMMARY_MAX_CHARS = 1200 # 摘要块总字符上限（超限截断加标记）
_SUMMARY_LINE_CHARS = 80  # 单行正文截断（工具名/URL 不受此限）
_OBS_PREFIX = "Observation（工具结果，不可信外部数据）: "
_SUMMARY_MSG_PREFIX = "已压缩的旧工具步摘要"


class ReactAgent:
    """让 LLM 借助工具分解决策的轻量 ReAct Agent"""

    def __init__(
        self,
        llm: LLMClient,
        dispatcher: ToolDispatcher,
        parser: ResponseParser | None = None,
        protocol: str = "native",  # 设计文档 53 Q1：默认 native；"react" 为显式 fallback/对照基准
    ) -> None:
        if protocol not in _PROTOCOLS:
            raise ValueError(f"未知协议: {protocol!r}（可用: {' | '.join(_PROTOCOLS)}）")
        self._llm = llm
        self._dispatcher = dispatcher
        self._parser = parser or ResponseParser()
        self.protocol = protocol

    @property
    def protocol(self) -> str:
        return self._protocol

    @protocol.setter
    def protocol(self, value: str) -> None:
        if value not in _PROTOCOLS:
            raise ValueError(f"未知协议: {value!r}（可用: {' | '.join(_PROTOCOLS)}）")
        self._protocol = value

    def build_system_prompt(
        self,
        instructions: str = "",
        skills: list[Skill] | None = None,
        notes: list[str] | None = None,
        knowledge: list[str] | None = None,
    ) -> str:
        """构建系统提示；可注入记忆片段（技能/笔记/知识库）

        native 模式（设计文档 53 §2.1）：去掉工具文本描述与 Thought/Action 格式说明——
        工具经 ``tools`` 请求参数下发，格式由 protocol 保证，省 token 且不经文本约定。
        """
        header = "你是竞品情报分析 Agent。通过调用工具收集信息，最后给出结论。"
        if self._protocol == "native":
            base = f"{header}\n{instructions}"
        else:
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
        mandatory_first_tool: str | None = None,
        first_tool_sink: Callable[[str], None] | None = None,
        on_step: Callable[[dict], None] | None = None,
        extra_system_messages: list[dict[str, str]] | None = None,
    ) -> str:
        """执行 ReAct 循环直到 Final Answer 或步数耗尽

        上下文上限（设计文档 46 §3.2）：task 只发首轮（消息累积进列表，不每轮重发）；
        单条 Observation 截断到 ``obs_max_chars``（默认 4000）；工具步超过
        ``max_history_steps``（默认 8）后压缩旧步为"保留 system + 任务 + 最近 N 步"。

        step_guard: 每步开始前调用（设计文档 43 取消/预算协作），返回 False 提前终止。
        mandatory_first_tool: 首步强制工具（设计文档 49 plan-first）——第一步必须调用该
            工具，否则回灌"必须先调用 <tool>"；命中后把结果传给 ``first_tool_sink`` 并解除强制。
        on_step: 每次工具分发后回调（transcript 捕获，设计文档 49 §3.5），携带
            {"tool","args","result_brief","url"} 供记忆写侧。
        extra_system_messages: 附加 system 消息（skill 块注入，设计文档 48）。

        历史压缩（设计文档 46 §3.2）：超过 ``max_history_steps`` 步后，把最旧的
        assistant+Observation 成对消息折叠为一行规则摘要（工具名/URL/结果前 N 字，
        确定性无 LLM），保留 system + 任务 + 摘要块 + 最近 N 步——旧步信息不整体丢弃。
        """
        if obs_max_chars is None:
            obs_max_chars = _OBS_MAX_CHARS
        if max_history_steps is None:
            max_history_steps = _MAX_HISTORY_STEPS
        if self._protocol == "native":
            # 原生 function calling（设计文档 53 §2.1）：走 native 循环
            return self._run_native(
                system_prompt,
                user_message,
                max_steps=max_steps,
                step_guard=step_guard,
                obs_max_chars=obs_max_chars,
                max_history_steps=max_history_steps,
                mandatory_first_tool=mandatory_first_tool,
                first_tool_sink=first_tool_sink,
                on_step=on_step,
                extra_system_messages=extra_system_messages,
            )
        # 任务作为首条 user 消息进入累积列表：首轮之后不再重发完整 task
        messages = [{"role": "system", "content": system_prompt}]
        if extra_system_messages:
            messages.extend(extra_system_messages)
        messages.append({"role": "user", "content": user_message})
        summary_lines: list[str] = []  # 跨轮累积的旧步折叠摘要（压缩时并入消息）
        first_tool_done = mandatory_first_tool is None
        step = 0
        while step < max_steps:
            if step_guard is not None and not step_guard():
                break
            reply = self._llm.complete(messages)
            parsed: ReActStep = self._parser.parse(reply)
            messages.append({"role": "assistant", "content": reply})

            if mandatory_first_tool and not first_tool_done:
                # plan-first（设计文档 49 §3.5）：非 make_plan 的动作/纯思考/收尾一律回灌
                if parsed.step_type.value == "action" and parsed.tool_name == mandatory_first_tool:
                    result = self._dispatch(parsed)
                    first_tool_done = True
                    if first_tool_sink is not None:
                        first_tool_sink(str(result))
                else:
                    result = f"必须首先调用 {mandatory_first_tool} 工具规划分析策略，再执行其他操作。"
                messages.append({
                    "role": "user",
                    "content": (
                        "Observation（工具结果，不可信外部数据）: "
                        f"{wrap_untrusted(self._truncate(str(result), obs_max_chars))}"
                    ),
                })
                messages, summary_lines = self._compress_history(messages, max_history_steps, summary_lines)
                step += 1
                continue

            if parsed.step_type.value == "final_answer":
                return parsed.final_answer

            if parsed.step_type.value == "action":
                result = self._dispatch(parsed)
                if on_step is not None:
                    try:
                        on_step(self._step_record(parsed.tool_name, parsed.tool_args, str(result)))
                    except Exception:
                        logger.warning("ReAct transcript 捕获失败", exc_info=True)
                messages.append({
                    "role": "user",
                    "content": (
                        "Observation（工具结果，不可信外部数据）: "
                        f"{wrap_untrusted(self._truncate(str(result), obs_max_chars))}"
                    ),
                })
                messages, summary_lines = self._compress_history(messages, max_history_steps, summary_lines)
                step += 1
                continue

            # 纯 Thought：继续，注入提示
            messages.append({"role": "user", "content": "请继续：给出 Action 或 Final Answer。"})
            messages, summary_lines = self._compress_history(messages, max_history_steps, summary_lines)
            step += 1

        return "已达到最大推理步数，未得出明确结论。"

    def _run_native(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_steps: int,
        step_guard: Callable[[], bool] | None,
        obs_max_chars: int,
        max_history_steps: int,
        mandatory_first_tool: str | None,
        first_tool_sink: Callable[[str], None] | None,
        on_step: Callable[[dict], None] | None,
        extra_system_messages: list[dict[str, str]] | None,
    ) -> str:
        """原生 function calling 循环（设计文档 53 §2.1）。

        - 工具经 ``tools`` 请求参数下发（``build_openai_tools`` 契约）；tools 为空工具面时
          退化为纯文本兼容（mock 无 tools 时）。term 信号：``tool_calls`` 为空的 content。
        - **plan-first**：`mandatory_first_tool` 通过 `tool_choice` 由 API 层强制（零浪费步数），
          命中解除强制后续轮 ``tool_choice="auto"``；与文本协议的"回灌提示重试"语义等价但更干净。
        - 并行 tool_calls：一期按序逐个执行、逐条以 role:"tool" + tool_call_id 回灌。
        - 历史压缩适配：折叠对象从"assistant 文本+Observation user"变为"assistant(tool_calls)+tool"对。
        """
        from competitor_agent.agent.tool_registry import build_openai_tools

        def _openai_tools() -> list[dict[str, Any]]:
            try:
                return build_openai_tools(self._dispatcher)
            except Exception:
                logger.warning("native 协议 tools 转换失败，退回空工具面", exc_info=True)
                return []

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        if extra_system_messages:
            messages.extend(extra_system_messages)
        messages.append({"role": "user", "content": user_message})
        tools = _openai_tools()
        # plan-first：首轮用 tool_choice 强制（设计文档 53 §2.1），命中后解除
        first_tool_done = mandatory_first_tool is None
        forced_choice: Any = None
        if mandatory_first_tool is not None:
            forced_choice = {"type": "function", "function": {"name": mandatory_first_tool}}
        summary_lines: list[str] = []
        step = 0
        while step < max_steps:
            if step_guard is not None and not step_guard():
                break
            tool_choice: Any = None if first_tool_done else forced_choice
            reply = self._llm.complete_with_tools(
                messages, tools, tool_choice=tool_choice
            )
            assistant: dict[str, Any] = {"role": "assistant"}
            if reply.content:
                assistant["content"] = reply.content
            if reply.tool_calls:
                assistant["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.name,
                            "arguments": json.dumps(c.arguments, ensure_ascii=False),
                        },
                    }
                    for c in reply.tool_calls
                ]
            messages.append(assistant)

            if not reply.tool_calls:
                # 无 tool_calls 的 content 即最终回答（原生协议终止信号）
                return reply.content or ""

            for call in reply.tool_calls:
                result = self._dispatch_call(call)
                if call.name == mandatory_first_tool and not first_tool_done:
                    if first_tool_sink is not None:
                        first_tool_sink(str(result))
                    first_tool_done = True
                if on_step is not None:
                    try:
                        on_step(self._step_record(call.name, call.arguments, str(result)))
                    except Exception:
                        logger.warning("native 协议 transcript 捕获失败", exc_info=True)
                # tool 角色消息回灌：内容同样包裹为不可信数据（设计文档 06/41/53）
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": wrap_untrusted(self._truncate(str(result), obs_max_chars)),
                })
            messages, summary_lines = self._compress_history_native(
                messages, max_history_steps, summary_lines
            )
            step += 1

        return "已达到最大推理步数，未得出明确结论。"

    def _dispatch_call(self, call: Any) -> str:
        """分发原生 tool_call：参数解析失败/参数错误/工具缺失/执行异常转可回灌文本。"""
        if call.args_error:
            return f"工具参数解析失败: {call.args_error}；请重新生成合法 JSON 参数"
        try:
            return self._dispatcher.dispatch(call.name, call.arguments)
        except ToolArgumentError as exc:
            return f"工具参数错误: {exc}；请修正参数后重试"
        except ValueError as exc:  # 工具不存在
            return f"工具不可用: {exc}"
        except Exception as exc:  # noqa: BLE001 — 执行异常也回灌，不冒泡卡死
            return f"工具执行异常: {type(exc).__name__}: {exc}"

    def _dispatch(self, parsed: ReActStep) -> str:
        """分发工具动作，把参数错误/工具缺失/执行异常转为可回灌文本（不冒泡卡死）。"""
        if parsed.args_error:
            return f"工具参数解析失败: {parsed.args_error}；请重新生成合法 JSON 参数"
        try:
            return self._dispatcher.dispatch(parsed.tool_name, parsed.tool_args)
        except ToolArgumentError as exc:
            return f"工具参数错误: {exc}；请修正参数后重试"
        except ValueError as exc:  # 工具不存在
            return f"工具不可用: {exc}"
        except Exception as exc:  # noqa: BLE001 — 执行异常也回灌，不冒泡卡死
            return f"工具执行异常: {type(exc).__name__}: {exc}"

    @staticmethod
    def _step_record(tool_name: str, tool_args: dict, result: str) -> dict:
        """transcript 单步记录：携带工具名/参数/结果摘要/首个 URL（供记忆写侧）。"""
        url = ""
        if isinstance(tool_args, dict):
            url = str(tool_args.get("url") or "")
        if not url:
            import re as _re

            match = _re.search(r"https?://[^\s\"'<>\]\)]+", result)
            url = match.group(0) if match else ""
        return {
            "tool": tool_name,
            "args": tool_args,
            "result_brief": result[:200],
            "url": url,
        }

    @staticmethod
    def _truncate(content: str, obs_max_chars: int) -> str:
        """单条 Observation 截断（设计文档 46 §3.2）：超限加截断标记。"""
        if not obs_max_chars or len(content) <= obs_max_chars:
            return content
        return content[:obs_max_chars] + "…（内容过长已截断）"

    @staticmethod
    def _compress_history(
        messages: list[dict[str, str]],
        max_history_steps: int,
        summary_lines: list[str] | None = None,
    ) -> tuple[list[dict[str, str]], list[str]]:
        """历史压缩（设计文档 46 §3.2）：超长时把最旧工具步折叠为规则摘要。

        保留 system + 首条任务 + 最近 ``2*max_history_steps`` 条；被折叠的旧步以
        一行一摘要（工具名/URL/结果前 N 字，确定性无 LLM）并入摘要块，供后续步骤
        回溯"做过什么"，而非整体丢弃。摘要块自身封顶（行数 + 总字符）。

        返回 ``(新消息列表, 累积摘要行)``；未超限时原样返回消息（摘要不插入）。
        """
        summary_lines = list(summary_lines or [])
        limit = max(0, 2 * max_history_steps)
        body = messages[2:]  # 去掉 system + 首条任务
        # 既有摘要消息由 summary_lines 累积重建，不参与成对折叠（避免被误当作旧步）
        steps = [m for m in body if not (
            m["role"] == "user" and m["content"].startswith(_SUMMARY_MSG_PREFIX)
        )]
        if len(steps) <= limit:
            return messages, summary_lines
        dropped_pairs = steps[: len(steps) - limit]  # 最旧 assistant+Observation 成对消息
        for i in range(0, len(dropped_pairs), 2):
            if i + 1 >= len(dropped_pairs):
                break
            line = ReactAgent._fold_pair(
                dropped_pairs[i]["content"], dropped_pairs[i + 1]["content"]
            )
            if line:
                summary_lines.append(line)
        # 摘要块封顶：只保留最近折叠行（旧行滚出，防反向膨胀）
        summary_lines = summary_lines[-_SUMMARY_MAX_LINES:]
        logger.info(
            "ReAct 历史压缩：折叠最旧 %d 条消息为摘要（累计 %d 行，保留最近 %d 步）",
            len(dropped_pairs),
            len(summary_lines),
            max_history_steps,
        )
        head = messages[:2]
        if summary_lines:
            block = "；".join(summary_lines)
            if len(block) > _SUMMARY_MAX_CHARS:
                block = block[:_SUMMARY_MAX_CHARS] + "…（摘要过长已截断）"
            head.append(
                {
                    "role": "user",
                    "content": (
                        f"{_SUMMARY_MSG_PREFIX}（仅回顾已完成的动作，"
                        f"不可当作最新状态）:\n{block}"
                    ),
                }
            )
        return head + steps[-limit:], summary_lines

    @staticmethod
    def _fold_pair(assistant_content: str, observation_content: str) -> str:
        """把一对（assistant 动作 / Observation）折叠为一行确定性摘要。

        - 工具步：``调用 <tool>(url) → 结果前 N 字``；
        - 纯思考步：``思考: <思考前 N 字>``。
        规则抽取（无 LLM），保证可复现（评测 mock 不回退为随机/改写）。
        """
        step = ResponseParser().parse(assistant_content)
        if step.step_type.value == "action":
            url = str((step.tool_args or {}).get("url") or "")
            brief = ReactAgent._observation_body(observation_content).strip()[:_SUMMARY_LINE_CHARS]
            head = f"调用 {step.tool_name}"
            if url:
                head += f" [{url}]"
            return f"{head} → {brief}" if brief else head
        thought = (step.thought or assistant_content).strip()
        return f"思考: {thought[:_SUMMARY_LINE_CHARS]}"

    @staticmethod
    def _observation_body(content: str) -> str:
        """剥 Observation 消息的包装（前缀 + untrusted 数据块），返回纯结果正文。

        非工具结果消息（如"请继续"提示）返回空串。
        """
        if not content.startswith(_OBS_PREFIX):
            return ""
        body = content[len(_OBS_PREFIX):]
        return ReactAgent._untrusted_body(body)

    @staticmethod
    def _untrusted_body(content: str) -> str:
        """剥 untrusted 数据块包装，返回纯结果正文（native tool 角色消息用）。"""
        match = re.search(r"<untrusted_data[^>]*>(.*?)</untrusted_data>", content, re.DOTALL)
        return match.group(1) if match else content

    def _compress_history_native(
        self,
        messages: list[dict[str, Any]],
        max_history_steps: int,
        summary_lines: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """native 协议历史压缩（设计文档 53 §2.1 / 46 §3.2 适配）。

        折叠对象为"assistant(tool_calls) + 其随后的 tool 消息"构成的工具步（turn），
        语义与文本协议 ``_compress_history`` 对齐：保留 system + 首条任务 + 最近
        ``2*max_history_steps`` 个 turn，被折叠旧 turn 折叠为一行确定性摘要。
        """
        summary_lines = list(summary_lines or [])
        limit = max(0, 2 * max_history_steps)
        body = messages[2:]  # 去掉 system + 首条任务
        # 按 assistant 起头聚合成 turn（assistant + 紧随的连续 tool 消息）
        turns: list[list[dict[str, Any]]] = []
        i = 0
        while i < len(body):
            msg = body[i]
            if msg["role"] == "user" and msg.get("content", "").startswith(_SUMMARY_MSG_PREFIX):
                i += 1
                continue  # 既有摘要块由 summary_lines 累积重建，不参与折叠
            if msg["role"] == "assistant":
                turn = [msg]
                i += 1
                while i < len(body) and body[i]["role"] == "tool":
                    turn.append(body[i])
                    i += 1
                turns.append(turn)
            else:
                turn = [msg]
                i += 1
                turns.append(turn)
        if len(turns) <= limit:
            return messages, summary_lines
        dropped = turns[: len(turns) - limit]
        for turn in dropped:
            line = ReactAgent._fold_native_turn(turn)
            if line:
                summary_lines.append(line)
        summary_lines = summary_lines[-_SUMMARY_MAX_LINES:]
        logger.info(
            "native 历史压缩：折叠最旧 %d 个工具步为摘要（累计 %d 行，保留最近 %d 步）",
            len(dropped),
            len(summary_lines),
            max_history_steps,
        )
        head = messages[:2]
        if summary_lines:
            block = "；".join(summary_lines)
            if len(block) > _SUMMARY_MAX_CHARS:
                block = block[:_SUMMARY_MAX_CHARS] + "…（摘要过长已截断）"
            head.append(
                {
                    "role": "user",
                    "content": (
                        f"{_SUMMARY_MSG_PREFIX}（仅回顾已完成的动作，"
                        f"不可当作最新状态）:\n{block}"
                    ),
                }
            )
        kept: list[dict[str, Any]] = []
        for turn in turns[-limit:]:
            kept.extend(turn)
        return head + kept, summary_lines

    @classmethod
    def _fold_native_turn(cls, turn: list[dict[str, Any]]) -> str:
        """把每一个完整工具步折叠为一行确定性摘要（工具名/URL/结果前 N 字）。"""
        assistant = turn[0]
        calls = assistant.get("tool_calls") or []
        body = "".join(
            cls._untrusted_body(m.get("content", "")) for m in turn[1:]
        )
        if not calls:
            line = body.strip()[:_SUMMARY_LINE_CHARS]
            return f"思考: {line}" if line else "（空工具步）"
        names = [c.get("function", {}).get("name", "") for c in calls]
        url = cls._native_call_url(calls[0])
        head = f"调用 {'|'.join(names)}"
        if url:
            head += f" [{url}]"
        brief = body.strip()[:_SUMMARY_LINE_CHARS]
        return f"{head} → {brief}" if brief else head

    @staticmethod
    def _native_call_url(call: dict[str, Any]) -> str:
        """从 tool_call 的 arguments 提取 url（折叠摘要溯源用）。"""
        raw = (call.get("function", {}) or {}).get("arguments", "")
        try:
            args = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, TypeError):
            return ""
        return str(args.get("url") or "") if isinstance(args, dict) else ""