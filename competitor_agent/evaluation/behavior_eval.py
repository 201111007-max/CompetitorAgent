"""行为级评测（设计文档 42）— 工具自恢复 + 检索命中率

- RecoveryEvaluator：对一组"会出错"的 ReAct 场景跑 mock LLM 脚本化回放——
  首轮故意输出非法参数/不存在工具 → 收到 Observation 回灌（设计文档 38 四类反馈）→
  第二轮输出合法调用 → 判定该场景自恢复；recovery_rate = 恢复场景 / 总场景（确定性、无 Key）。
- RetrievalEvaluator：用 (query, 期望 chunk) 夹具对每 query 分别以 hybrid / lexical
  检索 top_k，算 hit_rate@k；hybrid ≥ lexical 证明向量层收益，向量不可用时 hybrid==lexical
  （不误判劣）。

两 Evaluator 均无真实 Key/网络依赖，mock/real 评测模式都可复现。
"""
from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.agent.react_loop import ReactLoop
from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.knowledge_base.competitor_store import CompetitorStore, TextChunk
from competitor_agent.knowledge_base.retriever import Retriever
from competitor_agent.llm.client import LLMClient, ToolCallReply

# 设计文档 38 四类反馈关键词：ScriptedLLM 据此"读取" Observation 修正重试
_ERROR_MARKERS = ("工具参数错误", "工具不可用", "工具参数解析失败", "工具执行异常")


@dataclass
class BehaviorMetrics:
    """行为级评测指标（设计文档 42 §3.1）"""
    react_recovery_rate: float = 0.0   # 工具错误后自恢复成功比例
    recovery_n: int = 0                # 自恢复场景数
    retrieval_hit_hybrid: float = 0.0  # hybrid 命中率@k
    retrieval_hit_lexical: float = 0.0 # lexical 命中率@k（消融对照）
    retrieval_n: int = 0               # 检索样本数
    refetch_after_fold: int = 0        # 折叠后重复抓取次数（设计文档 56 M3，门禁 = 0）


@dataclass
class RecoveryScenario:
    """一个"会出错"的 ReAct 自恢复场景（脚本化回放输入）"""
    name: str
    task: str
    first_error: str                 # 出错轮输出：非法参数 / 不存在工具
    correction: str                  # 收到 Observation 回灌后输出：合法调用
    first_plan: str = (             # 首步 make_plan（设计文档 49 plan-first 强制）
        'Thought: 先规划分析策略\nAction: make_plan\n'
        'Args: {"plan_json": {"competitor": "cursor", "dimensions": ["pricing"]}}'
    )
    final_answer: str = "Final Answer: 自恢复成功"
    valid_tool: str = "web_extract"  # 应成功调用的合法工具
    valid_args: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalCase:
    """检索命中夹具：(query, 期望命中的 chunk_id)"""
    query: str
    competitor: str
    dimension: str
    expected: list[str] = field(default_factory=list)


def default_recovery_scenarios() -> list[RecoveryScenario]:
    """默认自恢复场景：工具参数错误 + 工具不可用两类（确定性、无网络）"""
    return [
        RecoveryScenario(
            name="bad_args_then_corrected",
            task="抓取 Cursor 定价页",
            first_error='Thought: 抓取定价页\n<action>web_extract({"url": 123})</action>',
            correction=(
                'Thought: url 应为字符串，修正参数\n'
                '<action>web_extract({"url": "https://cursor.com/pricing"})</action>'
            ),
            valid_tool="web_extract",
            valid_args={"url": "https://cursor.com/pricing"},
        ),
        RecoveryScenario(
            name="unknown_tool_then_fallback",
            task="查询 Cursor 定价",
            first_error='Thought: 用搜索工具\n<action>ghost_tool({"query": "cursor"})</action>',
            correction=(
                'Thought: ghost_tool 不可用，改用 web_search\n'
                '<action>web_search({"query": "Cursor 定价"})</action>'
            ),
            valid_tool="web_search",
            valid_args={"query": "Cursor 定价"},
        ),
    ]


def _default_seed_chunks() -> list[TextChunk]:
    """默认检索夹具灌库：query 与期望 chunk 有明确 token 重叠（确定性、可复现）"""
    return [
        TextChunk("cursor_p1", "cursor", "pricing", "cursor pro plan costs $20 per month", ""),
        TextChunk("cursor_p2", "cursor", "pricing", "cursor team plan costs $40 per month", ""),
        TextChunk("cursor_f1", "cursor", "feature", "cursor supports ai autocomplete for code editing", ""),
        TextChunk("claude_c1", "claude", "feature", "claude code cli supports terminal workflows", ""),
        TextChunk("claude_c2", "claude", "pricing", "claude pro plan costs $20 per month", ""),
    ]


def default_retrieval_cases() -> list[RetrievalCase]:
    """默认检索夹具：(query, competitor, dimension, 期望 chunk_id)"""
    return [
        RetrievalCase("cursor pro plan costs $20", "cursor", "pricing", ["cursor_p1"]),
        RetrievalCase("cursor team plan costs $40", "cursor", "pricing", ["cursor_p2"]),
        RetrievalCase("cursor ai autocomplete for code", "cursor", "feature", ["cursor_f1"]),
        RetrievalCase("claude code cli terminal", "claude", "feature", ["claude_c1"]),
        RetrievalCase("claude pricing pro $20", "claude", "pricing", ["claude_c2"]),
    ]


class ScriptedLLM:
    """确定性脚本化 mock LLM：首步 make_plan → 故意输出错误 → 收到回灌后修正（自恢复）

    第 1 轮输出 first_plan（make_plan，设计文档 49 plan-first）；第 2 轮输出 first_error
    （非法参数/不存在工具）；第 3 轮若 Observation 含设计文档 38 错误反馈关键词则输出
    correction（合法调用）；之后输出 final_answer。无真实 Key 依赖。
    """

    def __init__(self, scenario: RecoveryScenario) -> None:
        self._scenario = scenario
        self._round = 0

    def complete(self, messages: list[dict[str, str]], model: str | None = None, **kwargs: Any) -> Any:
        self._round += 1
        if self._round == 1:
            text = self._scenario.first_plan
        elif self._round == 2:
            text = self._scenario.first_error
        # 第 3 轮起：读最近一条 Observation（react_agent 把 task 追加在 Observation 之后，
        # 故按内容前缀定位），含设计文档 38 错误反馈关键词即输出合法调用（自恢复）
        elif self._round == 3 and any(m in self._last_observation(messages) for m in _ERROR_MARKERS):
            text = self._scenario.correction
        else:
            text = self._scenario.final_answer
        if kwargs.get("tools"):
            return self._to_tool_reply(text)
        return text

    @staticmethod
    def _to_tool_reply(text: str) -> ToolCallReply:
        """把脚本化文本映射为 native 等价物：兼容 plan-first（Action:/Args:）与 <action> 两种格式。"""
        from competitor_agent.llm.client import ToolCall, ToolCallReply

        if text.startswith("Final Answer: "):
            return ToolCallReply(content=text[len("Final Answer: "):])
        name: str | None = None
        args_str: str | None = None
        tag = re.search(r"<action>(\w+)\((.*?)\)</action>", text, re.DOTALL)
        if tag:
            name, args_str = tag.group(1), tag.group(2)
        else:
            action = re.search(r"Action:\s*(\w+)", text)
            if action:
                name = action.group(1)
                args_m = re.search(r"Args:\s*(\{.*\})", text, re.DOTALL)
                args_str = args_m.group(1) if args_m else None
        if not name:
            return ToolCallReply(content=text)
        arguments: dict[str, Any] = {}
        if args_str is not None and args_str.strip():
            try:
                parsed = json.loads(args_str)
                if isinstance(parsed, dict):
                    arguments = parsed
            except (json.JSONDecodeError, TypeError):
                pass
        return ToolCallReply(
            tool_calls=[ToolCall(id="call_0", name=name, arguments=arguments)]
        )

    @staticmethod
    def _last_observation(messages: list[dict[str, str]]) -> str:
        for message in reversed(messages):
            role = message.get("role")
            content = str(message.get("content", ""))
            if role == "tool" or (role == "user" and "Observation" in content):
                return content
        return ""


class RecoveryEvaluator:
    """ReAct 自恢复评测：ScriptedLLM 回放错误→回灌→修正→成功（设计文档 42 §3.1）

    驱动 ReactLoop（agent/react_loop.py），对每个场景判定"是否出现错误→是否恢复"：
    恢复 = 修正后的合法工具调用真的成功分发（工具函数被调用，schema 校验通过）且循环产出结论。
    """

    def __init__(self, llm: LLMClient | None = None, dispatcher: ToolDispatcher | None = None) -> None:
        self._llm = llm            # 注入自定义 mock（如"永不恢复"脚本）；None 用 ScriptedLLM
        self._dispatcher = dispatcher

    def run(self, scenarios: list[RecoveryScenario] | None = None) -> tuple[float, int]:
        """返回 (react_recovery_rate, recovery_n)"""
        scenarios = list(scenarios) if scenarios is not None else default_recovery_scenarios()
        if not scenarios:
            return 0.0, 0
        recovered = 0
        for scenario in scenarios:
            recorder: list[dict[str, Any]] = []
            dispatcher = self._dispatcher or self._build_dispatcher(recorder)
            llm = self._llm or LLMClient(call_func=ScriptedLLM(scenario).complete)
            agent = ReactAgent(llm=llm, dispatcher=dispatcher)
            # plan_first：首步强制 make_plan（设计文档 49），与主路径 Lead 语义一致
            answer = ReactLoop(agent, plan_first=True).run(scenario.task)
            if _scenario_recovered(scenario, answer, recorder):
                recovered += 1
        return round(recovered / len(scenarios), 4), len(scenarios)

    @staticmethod
    def _build_dispatcher(recorder: list[dict[str, Any]]) -> ToolDispatcher:
        """多工具 dispatcher（复用设计文档 40 唯一工具源 TOOL_SPECS）：
        web_extract 用无网络假实现；成功分发即记录（证明修正后合法调用真执行，而非仅 Final Answer）。"""
        from competitor_agent.mcp_server.tools import TOOL_SPECS, TOOLS

        def fake_web_extract(url: str, selector: str = "") -> str:
            return f"REACT_EXTRACT:{url}"

        def record(name: str, func: Callable[..., str]) -> Callable[..., str]:
            def wrapped(**kwargs: Any) -> str:
                result = func(**kwargs)
                recorder.append({"tool": name, "args": kwargs})
                return result
            return wrapped

        dispatcher = ToolDispatcher()
        for name, spec in TOOL_SPECS.items():
            func = fake_web_extract if name == "web_extract" else TOOLS[name]
            dispatcher.register(name, record(name, func), spec=spec)
        # plan-first 首步强制工具（设计文档 49），Lead 与子 Agent 同源
        from competitor_agent.agent.make_plan import make_plan as _make_plan

        dispatcher.register("make_plan", record("make_plan", _make_plan))
        return dispatcher


def _scenario_recovered(scenario: RecoveryScenario, answer: str, recorder: list[dict[str, Any]]) -> bool:
    """恢复判定：修正后的合法工具调用成功分发（schema 校验通过、工具函数被调用）且产出结论。"""
    if not answer:
        return False
    return any(
        call.get("tool") == scenario.valid_tool and call.get("args") == scenario.valid_args
        for call in recorder
    )


class RetrievalEvaluator:
    """RAG 命中评测：对夹具跑 hybrid vs lexical → hit_rate@k（设计文档 42 §3.1）

    hybrid ≥ lexical 证明向量层收益；向量层不可用时 hybrid 自动降级词袋 == lexical（不误判劣）。
    """

    def __init__(self, retriever: Retriever | None = None, top_k: int = 3) -> None:
        self._retriever = retriever
        self._top_k = top_k

    def run(self, cases: list[RetrievalCase] | None = None) -> tuple[float, float, int]:
        """返回 (hit_hybrid, hit_lexical, n)"""
        cases = list(cases) if cases is not None else default_retrieval_cases()
        if not cases:
            return 0.0, 0.0, 0
        retriever = self._retriever or self._build_retriever()
        hit_hybrid = 0
        hit_lexical = 0
        for case in cases:
            expected = set(case.expected)
            hybrid = retriever.retrieve(
                case.query, case.competitor, dimension=case.dimension,
                top_k=self._top_k, strategy="hybrid",
            )
            lexical = retriever.retrieve(
                case.query, case.competitor, dimension=case.dimension,
                top_k=self._top_k, strategy="lexical",
            )
            if expected & {c.chunk_id for c in hybrid}:
                hit_hybrid += 1
            if expected & {c.chunk_id for c in lexical}:
                hit_lexical += 1
        n = len(cases)
        return round(hit_hybrid / n, 4), round(hit_lexical / n, 4), n

    @staticmethod
    def _build_retriever() -> Retriever:
        """灌默认夹具：可注入哈希向量层（确定性离线）；chromadb 缺失则降级词袋（hybrid==lexical）。"""
        vector_store = None
        try:
            import chromadb  # noqa: F401

            from competitor_agent.knowledge_base.vector_store import VectorStore

            vector_store = VectorStore(embed_fn="hash")
        except Exception:  # noqa: BLE001 - chromadb 缺失降级词袋 # pragma: no cover
            vector_store = None
        store = CompetitorStore(
            data_dir=Path(tempfile.mkdtemp(prefix="behavior_retrieval_")),
            vector_store=vector_store,
        )
        for chunk in _default_seed_chunks():
            store.add(chunk)
        return Retriever(store=store)


class FoldRecallScriptedLLM:
    """折叠取回对照脚本（设计文档 56 M3）：>max_history_steps 步后上下文已压缩。

    前 ``n_fetches`` 轮逐个抓取不同 URL，第 n_fetches+1 轮调 validate_facts
    （产生一条 pinned 已核验事实）；之后的决策轮"需要"最早抓取的 p0 内容：
    摘要块含 kb_recall 指引 → 调 kb_recall 取回（可逆闭环）；指引缺失（修复前
    形状）→ 只能重发 web_extract 重抓（重复抓取 +1）。决策完全由上下文驱动，
    因此同一脚本可直接量化修复前后差异（refetch_after_fold: >0 → 0）。
    """

    P0_URL = "https://example.com/pricing-p0"

    def __init__(self, n_fetches: int = 9) -> None:
        self.calls: list[list[dict[str, Any]]] = []
        self._round = 0
        self._n_fetches = n_fetches
        self._decision_done = False

    def complete(self, messages: list[dict[str, str]], model: str | None = None, **kwargs: Any) -> Any:
        """原生形状脚本（设计文档 60：单协议）：动作步返回带 ToolCall 的 ToolCallReply，
        ``tool_calls`` 为空（纯 content）即最终回答终止信号。"""
        from competitor_agent.llm.client import ToolCall, ToolCallReply

        self.calls.append([dict(m) for m in messages])
        self._round += 1
        if self._round <= self._n_fetches:
            url = f"https://example.com/pricing-p{self._round - 1}"
            return self._tool_reply(ToolCall(id=f"call_{self._round}", name="web_extract", arguments={"url": url}))
        if self._round == self._n_fetches + 1:
            return self._tool_reply(
                ToolCall(
                    id=f"call_{self._round}",
                    name="validate_facts",
                    arguments={
                        "details_json": {"monthly_price_usd": 20},
                        "raw_text": "cursor pro plan costs $20 per month",
                    },
                )
            )
        if not self._decision_done:
            self._decision_done = True
            summary = self._summary_block(messages)
            if "kb_recall" in summary:
                return self._tool_reply(
                    ToolCall(id=f"call_{self._round}", name="kb_recall", arguments={"query": "cursor pro plan pricing p0"})
                )
            return self._tool_reply(
                ToolCall(id=f"call_{self._round}", name="web_extract", arguments={"url": self.P0_URL})
            )
        return ToolCallReply(content="cursor pro 定价 $20/月")

    @staticmethod
    def _tool_reply(call: Any) -> Any:
        from competitor_agent.llm.client import ToolCallReply

        return ToolCallReply(tool_calls=[call])

    @staticmethod
    def _summary_block(messages: list[dict[str, str]]) -> str:
        from competitor_agent.agent.react_agent import _SUMMARY_MSG_PREFIX

        for message in reversed(messages):
            content = str(message.get("content", ""))
            if message.get("role") == "user" and content.startswith(_SUMMARY_MSG_PREFIX):
                return content
        return ""

    @property
    def last_messages(self) -> list[dict[str, Any]]:
        return self.calls[-1] if self.calls else []


class FoldRecallEvaluator:
    """折叠取回对照评测（设计文档 56 M3）：压缩发生后模型应 kb_recall 取回而非重抓。

    返回 ``(refetch_after_fold, pinned_survived)``：重复抓取次数（同一 URL 抓取
    第二次起计一次，门禁 = 0）+ pinned 段在压缩后是否仍在消息列表（M2 断言）。
    全链路确定性（ScriptedLLM + 假 web_extract/kb_recall），无 Key/网络依赖。
    """

    def run(self, max_history_steps: int = 8) -> tuple[int, bool]:
        from competitor_agent.agent.react_agent import _PINNED_MSG_PREFIX
        from competitor_agent.agent.review_tools import (
            build_validate_facts_tool,
            extract_verified_facts,
        )

        fetched: list[str] = []

        def fake_web_extract(url: str) -> str:
            fetched.append(url)
            return f"cursor pro plan costs $20 per month (page {url})"

        def fake_kb_recall(query: str) -> str:
            return "RECALLED: cursor pro plan costs $20 per month"

        dispatcher = ToolDispatcher()
        dispatcher.register("web_extract", fake_web_extract)
        dispatcher.register("kb_recall", fake_kb_recall)
        dispatcher.register("validate_facts", build_validate_facts_tool())
        scripted = FoldRecallScriptedLLM()
        agent = ReactAgent(
            llm=LLMClient(call_func=scripted.complete),
            dispatcher=dispatcher,
        )
        pinned_facts: list[str] = []
        loop = ReactLoop(
            agent,
            max_steps=20,
            max_history_steps=max_history_steps,
            pinned_facts=pinned_facts,
            on_step=lambda rec: pinned_facts.extend(extract_verified_facts(rec)),
        )
        loop.run("分析 cursor 定价（折叠取回对照实验）")
        refetch = len(fetched) - len(set(fetched))
        pinned_survived = any(
            str(m.get("content", "")).startswith(_PINNED_MSG_PREFIX)
            for m in scripted.last_messages
            if m.get("role") == "user"
        )
        return refetch, pinned_survived


__all__ = [
    "BehaviorMetrics",
    "FoldRecallEvaluator",
    "FoldRecallScriptedLLM",
    "RecoveryEvaluator",
    "RecoveryScenario",
    "RetrievalCase",
    "RetrievalEvaluator",
    "ScriptedLLM",
    "default_recovery_scenarios",
    "default_retrieval_cases",
]
