"""CompetitorReActAgent — 竞品分析 function calling 交互层

组装：系统提示 → 循环调用 LLM（原生 function calling）+ ToolDispatcher，
产出最终回答或用 LLM 语义分析 Observation。

设计文档 60：单协议（原生 function calling），删除文本 ReAct 协议。
工具经 ``tools`` 请求参数下发，无需在 system prompt 里写格式说明。
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from competitor_agent.agent.prompts.react_system import enrich_prompt
from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted
from competitor_agent.agent.tool_dispatcher import ToolArgumentError, ToolDispatcher
from competitor_agent.interfaces.context import Skill
from competitor_agent.llm.client import LLMClient
from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.react_agent")

# 上下文上限（设计文档 46 §3.2）：长页面/多轮工具结果不失控
_OBS_MAX_CHARS = 4000   # 单条 Observation 截断（循环内，防上下文膨胀）
_MAX_HISTORY_STEPS = 8  # 超过后把旧工具步折叠为摘要（保留 system + 任务 + 最近 N 步）
# 压缩摘要块自身上限：折叠是"一行一旧步"，行数与总字符都要封顶，防摘要块反向膨胀
_SUMMARY_MAX_LINES = 6    # 最多保留最近折叠行数
_SUMMARY_MAX_CHARS = 1200 # 摘要块总字符上限（超限截断加标记）
_SUMMARY_LINE_CHARS = 80  # 单行正文截断（工具名/URL 不受此限）
_SUMMARY_MSG_PREFIX = "已压缩的旧工具步摘要"
# 设计文档 56 M1③：摘要指引可操作化——告知模型折叠步全文的取回途径（kb_recall）
_SUMMARY_MSG_GUIDANCE = (
    "仅回顾已完成的动作，不可当作最新状态；"
    "折叠步的完整内容已摄入知识库，可用 kb_recall(query) 取回"
)
# 设计文档 56 M2：已核验事实 pinning——独立 user 消息固定在摘要块后，永不折叠/滚出
_PINNED_MSG_PREFIX = "已核验事实（经复核工具核验，压缩后保留，可直接引用）"
_PINNED_MAX_LINES = 8    # pinned 段行数上限（超限只保最近核验）
_PINNED_LINE_CHARS = 120 # pinned 单行字符上限


class ReactAgent:
    """让 LLM 借助工具分解决策的轻量 function calling Agent（设计文档 60：单协议）"""

    def __init__(
        self,
        llm: LLMClient,
        dispatcher: ToolDispatcher,
        max_parallel_tool_calls: int = 4,
    ) -> None:
        """``max_parallel_tool_calls``：单回合多 tool_calls 的并发上限（设计文档 59）。

        1 = 完全串行（回归现状）；默认 4 并发分发、按原序收集。工具需线程安全（契约见 doc 59 §3.3）。
        """
        self._llm = llm
        self._dispatcher = dispatcher
        self._max_parallel_tool_calls = max_parallel_tool_calls

    def build_system_prompt(
        self,
        instructions: str = "",
        skills: list[Skill] | None = None,
        notes: list[str] | None = None,
        knowledge: list[str] | None = None,
    ) -> str:
        """构建系统提示；可注入记忆片段（技能/笔记/知识库）

        设计文档 53 §2.1：工具经 ``tools`` 请求参数下发，system prompt 不含
        工具文本描述与 Thought/Action 格式说明（省 token，格式由协议保证）。
        """
        header = "你是竞品情报分析 Agent。通过调用工具收集信息，最后给出结论。"
        base = f"{header}\n{instructions}"
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
        pinned_facts: list[str] | None = None,
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
        pinned_facts: 已核验事实清单（设计文档 56 M2，共享可变列表，由 on_step 收集侧
            追加）；压缩时重建为 pinned 段固定在摘要块之后，永不折叠/滚出。

        历史压缩（设计文档 46 §3.2）：超过 ``max_history_steps`` 步后，把最旧的
        assistant+Observation 成对消息折叠为一行规则摘要（工具名/URL/结果前 N 字，
        确定性无 LLM），保留 system + 任务 + 摘要块 + 最近 N 步——旧步信息不整体丢弃。
        """
        if obs_max_chars is None:
            obs_max_chars = _OBS_MAX_CHARS
        if max_history_steps is None:
            max_history_steps = _MAX_HISTORY_STEPS
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
            pinned_facts=pinned_facts,
        )

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
        pinned_facts: list[str] | None,
    ) -> str:
        """原生 function calling 循环（设计文档 53 §2.1，唯一循环，设计文档 60）。

        - 工具经 ``tools`` 请求参数下发（``build_openai_tools`` 契约）。终止信号：
          ``tool_calls`` 为空的 content 即最终回答。
        - **plan-first**：`mandatory_first_tool` 通过 `tool_choice` 由 API 层强制（零浪费步数），
          命中解除强制后续轮 ``tool_choice="auto"``。
        - 并行 tool_calls：按序逐个执行、逐条以 role:"tool" + tool_call_id 回灌。
        - 历史压缩：折叠"assistant(tool_calls)+其 tool 消息"构成的对为确定性摘要。
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

            results = self._dispatch_in_parallel(reply.tool_calls)
            # 后续 first_tool_sink / on_step / tool 回灌 / 压缩全部遍历 results（原序），逐字节不变
            for call, result in results:
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
            messages, summary_lines = self._compress_history(
                messages, max_history_steps, summary_lines, pinned_facts
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

    def _dispatch_in_parallel(self, calls: list[Any]) -> list[tuple[Any, str]]:
        """并发分发 + 原序收集（设计文档 59 §2/§3.1）。

        单 tool_call 或 ``max_parallel_tool_calls<=1`` 走串行（现状路径）；否则
        ThreadPoolExecutor 并发 submit，结果按 ``calls`` 原序收集——transcript/tool
        回灌遍历顺序与串行逐字节一致。``_dispatch_call`` 已把错误转可回灌文本、不冒泡，
        单个 future 失败不影响其他工具（隔离语义不变）。
        """
        if len(calls) <= 1 or self._max_parallel_tool_calls <= 1:
            return [(call, self._dispatch_call(call)) for call in calls]
        from concurrent.futures import ThreadPoolExecutor

        executor = ThreadPoolExecutor(
            max_workers=min(len(calls), self._max_parallel_tool_calls)
        )
        try:
            futures = [(call, executor.submit(self._dispatch_call, call)) for call in calls]
            return [(call, fut.result()) for call, fut in futures]
        finally:
            executor.shutdown(wait=True)

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
    def _pinned_message(pinned_facts: list[str] | None) -> dict[str, str] | None:
        """pinned 段消息（设计文档 56 M2）：已核验事实一行一条，行数+单行字符双封顶。

        超限只保最近核验（旧核验结论已沉淀进报告 details）；无核验事实时不插入空段。
        """
        if not pinned_facts:
            return None
        lines = [line[:_PINNED_LINE_CHARS] for line in pinned_facts[-_PINNED_MAX_LINES:]]
        return {
            "role": "user",
            "content": f"{_PINNED_MSG_PREFIX}:\n" + "\n".join(f"- {line}" for line in lines),
        }

    @staticmethod
    def _untrusted_body(content: str) -> str:
        """剥 untrusted 数据块包装，返回纯结果正文（native tool 角色消息用）。"""
        match = re.search(r"<untrusted_data[^>]*>(.*?)</untrusted_data>", content, re.DOTALL)
        return match.group(1) if match else content

    @staticmethod
    def _compress_history(
        messages: list[dict[str, Any]],
        max_history_steps: int,
        summary_lines: list[str] | None = None,
        pinned_facts: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """历史压缩（设计文档 46 §3.2 / 53 §2.1 适配，唯一实现）。

        折叠对象为"assistant(tool_calls) + 其随后的 tool 消息"构成的工具步（turn）：
        保留 system + 首条任务 + 最近 ``2*max_history_steps`` 个 turn，被折叠旧
        turn 折叠为一行确定性摘要（无 LLM）。
        """
        summary_lines = list(summary_lines or [])
        limit = max(0, 2 * max_history_steps)
        body = messages[2:]  # 去掉 system + 首条任务
        # 按 assistant 起头聚合成 turn（assistant + 紧随的连续 tool 消息）
        turns: list[list[dict[str, Any]]] = []
        i = 0
        while i < len(body):
            msg = body[i]
            if msg["role"] == "user" and msg.get("content", "").startswith(
                (_SUMMARY_MSG_PREFIX, _PINNED_MSG_PREFIX)
            ):
                i += 1
                continue  # 既有摘要/pinned 块由 summary_lines/pinned_facts 累积重建，不参与折叠
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
                    "content": f"{_SUMMARY_MSG_PREFIX}（{_SUMMARY_MSG_GUIDANCE}）:\n{block}",
                }
            )
        pinned_msg = ReactAgent._pinned_message(pinned_facts)
        if pinned_msg is not None:
            head.append(pinned_msg)
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