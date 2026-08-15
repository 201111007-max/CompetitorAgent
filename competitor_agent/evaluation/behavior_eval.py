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

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.agent.react_loop import ReactLoop
from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.knowledge_base.competitor_store import CompetitorStore, TextChunk
from competitor_agent.knowledge_base.retriever import Retriever
from competitor_agent.llm.client import LLMClient

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


@dataclass
class RecoveryScenario:
    """一个"会出错"的 ReAct 自恢复场景（脚本化回放输入）"""
    name: str
    task: str
    first_error: str                 # 首轮输出：非法参数 / 不存在工具
    correction: str                  # 收到 Observation 回灌后输出：合法调用
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
    """确定性脚本化 mock LLM：首轮故意输出错误，收到 Observation 回灌后修正（自恢复）

    第 1 轮输出 first_error（非法参数/不存在工具）；第 2 轮若 Observation 含设计文档 38
    错误反馈关键词则输出 correction（合法调用）；之后输出 final_answer。无真实 Key 依赖。
    """

    def __init__(self, scenario: RecoveryScenario) -> None:
        self._scenario = scenario
        self._round = 0

    def complete(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        self._round += 1
        if self._round == 1:
            return self._scenario.first_error
        # 第 2 轮后：读最近一条 Observation（react_agent 把 task 追加在 Observation 之后，
        # 故按内容前缀定位），含设计文档 38 错误反馈关键词即输出合法调用（自恢复）
        if self._round == 2 and any(m in self._last_observation(messages) for m in _ERROR_MARKERS):
            return self._scenario.correction
        return self._scenario.final_answer

    @staticmethod
    def _last_observation(messages: list[dict[str, str]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user" and "Observation" in message.get("content", ""):
                return message.get("content", "")
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
            answer = ReactLoop(agent).run(scenario.task)
            if _scenario_recovered(scenario, answer, recorder):
                recovered += 1
        return round(recovered / len(scenarios), 4), len(scenarios)

    @staticmethod
    def _build_dispatcher(recorder: list[dict[str, Any]]) -> ToolDispatcher:
        """多工具 dispatcher（复用设计文档 40 唯一工具源 TOOL_SPECS）：
        web_extract 用无网络假实现；成功分发即记录（证明修正后合法调用真执行，而非仅 Final Answer）。"""
        from competitor_agent.mcp_server.tools import TOOLS, TOOL_SPECS

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
        except Exception:  # pragma: no cover - 无 chromadb 环境降级词袋
            vector_store = None
        store = CompetitorStore(
            data_dir=Path(tempfile.mkdtemp(prefix="behavior_retrieval_")),
            vector_store=vector_store,
        )
        for chunk in _default_seed_chunks():
            store.add(chunk)
        return Retriever(store=store)


__all__ = [
    "BehaviorMetrics",
    "RecoveryEvaluator",
    "RecoveryScenario",
    "RetrievalCase",
    "RetrievalEvaluator",
    "ScriptedLLM",
    "default_recovery_scenarios",
    "default_retrieval_cases",
]
