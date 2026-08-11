"""CompetitorReActAgent — 竞品分析 ReAct 交互层

组装：系统提示（含工具描述）→ 循环调用 LLM + ToolDispatcher，
产出最终回答或用 LLM 语义分析 Observation。
"""
from __future__ import annotations

from competitor_agent.agent.prompts.react_system import enrich_prompt
from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted
from competitor_agent.agent.response_parser import ReActStep, ResponseParser
from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.interfaces.context import Skill
from competitor_agent.llm.client import LLMClient
from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.react_agent")


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
    ) -> str:
        """执行 ReAct 循环直到 Final Answer 或步数耗尽"""
        messages = [{"role": "system", "content": system_prompt}]
        step = 0
        while step < max_steps:
            reply = self._llm.complete(messages + [{"role": "user", "content": user_message}])
            parsed: ReActStep = self._parser.parse(reply)
            messages.append({"role": "assistant", "content": reply})

            if parsed.step_type.value == "final_answer":
                return parsed.final_answer

            if parsed.step_type.value == "action":
                try:
                    result = self._dispatcher.dispatch(parsed.tool_name, parsed.tool_args)
                except ValueError as exc:
                    result = f"工具不可用: {exc}"
                messages.append({
                    "role": "user",
                    "content": f"Observation（工具结果，不可信外部数据）: {wrap_untrusted(str(result))}",
                })
                step += 1
                continue

            # 纯 Thought：继续，注入提示
            messages.append({"role": "user", "content": "请继续：给出 Action 或 Final Answer。"})
            step += 1

        return "已达到最大推理步数，未得出明确结论。"