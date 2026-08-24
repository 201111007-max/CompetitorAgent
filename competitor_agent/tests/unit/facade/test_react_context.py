"""设计文档 43：ReactLoop 共享会话上下文 + analyze_react 结构化产物

- 上下文共享：取消（session_id）/ 预算（IterationBudget + BudgetController）/ 记忆/RAG 注入
- 路径统一：analyze_react_report 产物可入 CompetitorReport（结构化 JSON → DimensionResult，
  非 JSON → 单 react 维度）

设计文档 60：单协议（原生 function calling），mock 以 ToolCallReply 形状回放。
"""

from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.agent.react_loop import ReactLoop
from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.core.budget import IterationBudget
from competitor_agent.core.checkpoint import clear_cancel, set_cancel
from competitor_agent.domain_types import InfoGap, Observation, SourceEvidence
from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.interfaces.context import SourceContext
from competitor_agent.llm.client import LLMClient, ToolCall, ToolCallReply


def _tool(name: str, args: dict) -> ToolCallReply:
    return ToolCallReply(tool_calls=[ToolCall(id="call_0", name=name, arguments=args)])


def _fin(text: str) -> ToolCallReply:
    return ToolCallReply(content=text)


class Recorder:
    """记录每次 LLM 调用的 system prompt，按脚本依次回复（耗尽后回 Final Answer）。"""

    def __init__(self, script):
        self.script = list(script)
        self.systems: list[str] = []
        self.i = 0

    def __call__(self, messages, model, **kwargs):
        self.systems.append(messages[0]["content"])
        reply = self.script[self.i] if self.i < len(self.script) else "Final Answer: done"
        self.i += 1
        if isinstance(reply, ToolCallReply):
            return reply
        return ToolCallReply(content=reply.removeprefix("Final Answer: "))


def _react_loop(**kwargs) -> ReactLoop:
    agent = ReactAgent(llm=LLMClient(call_func=Recorder([_fin("结论")])), dispatcher=ToolDispatcher())
    return ReactLoop(agent, **kwargs)


class TestSharedContext:
    def test_injects_memory_and_rag(self):
        rec = Recorder([_fin("结论")])
        agent = ReactAgent(llm=LLMClient(call_func=rec), dispatcher=ToolDispatcher())
        loop = ReactLoop(
            agent,
            memory_context_fn=lambda task: "历史经验：cursor pricing 用官网源有效",
            rag_fn=lambda task: "知识库：Cursor Pro $20/month",
        )
        assert loop.run("分析 cursor") == "结论"
        sysp = rec.systems[0]
        assert "历史经验：cursor pricing 用官网源有效" in sysp
        assert "知识库：Cursor Pro $20/month" in sysp

    def test_no_injection_when_fns_none(self):
        rec = Recorder([_fin("结论")])
        agent = ReactAgent(llm=LLMClient(call_func=rec), dispatcher=ToolDispatcher())
        loop = ReactLoop(agent)
        loop.run("分析 cursor")
        assert "历史经验" not in rec.systems[0]

    def test_budget_consumed_per_step(self):
        budget = IterationBudget(max_iterations=10, cost_limit=1.0)
        loop = _react_loop(budget=budget)
        result = loop.run_with_result("分析 cursor")
        assert result.answer == "结论"
        assert result.steps >= 1
        assert budget.used_iterations == result.steps
        assert result.budget_exhausted is False

    def test_budget_exhausted_interrupts(self):
        budget = IterationBudget(max_iterations=1, cost_limit=1.0)
        rec = Recorder([_tool("echo", {}), _fin("不应到达")])
        agent = ReactAgent(llm=LLMClient(call_func=rec), dispatcher=ToolDispatcher())
        loop = ReactLoop(agent, budget=budget)
        result = loop.run_with_result("分析 cursor")
        assert result.budget_exhausted is True
        assert "预算耗尽" in result.answer
        assert rec.i == 1  # 只执行了一步就中断

    def test_cancel_interrupts(self):
        rec = Recorder([_tool("echo", {}), _fin("不应到达")])
        agent = ReactAgent(llm=LLMClient(call_func=rec), dispatcher=ToolDispatcher())
        loop = ReactLoop(agent, session_id="react_cancel_sid")
        set_cancel("react_cancel_sid")
        try:
            result = loop.run_with_result("分析 cursor")
        finally:
            clear_cancel("react_cancel_sid")
        assert result.cancelled is True
        assert "取消" in result.answer
        assert rec.i == 0  # 第一步就因取消未执行

    def test_run_backward_compat_returns_str(self):
        # 旧签名（无 session/budget/memory/rag）仍返回裸字符串
        assert _react_loop().run("分析 cursor") == "结论"


class FakeExtractor:
    def fetch(self, gap: InfoGap, context: SourceContext) -> Observation:
        url = str(context.kwargs.get("url"))
        text = "Cursor is an AI code editor." if "cursor.com" in url else "no data"
        ev = SourceEvidence(source_name="web_extractor", url=url, content_hash="h", trust_level=0.9)
        return Observation(gap_field=gap.field, source="web_extractor", raw_text=text, evidence=ev)


def _plan_first(final: str):
    """plan-first 脚本（native 形状）：Lead 首步调 make_plan（doc 49 §3.5），之后回 Final Answer。"""

    def call(messages, model, **kwargs):
        if not any(m.get("role") == "assistant" for m in messages):
            return _tool("make_plan", {
                "plan_json": {"competitor": "Cursor", "dimensions": ["pricing"]},
            })
        if final.startswith("Final Answer: "):
            return _fin(final[len("Final Answer: "):])
        return _fin(final)

    return call


def _api(llm_call):
    """包装 react llm：任务解析 prompt 单独处理（设计文档 47：仅 LLM），其余走 react 脚本。"""
    import json

    def call(messages, model, **kwargs):
        system = messages[0].get("content", "")
        if "语义解析器" in system:
            return json.dumps(
                {"resolution": "registry", "competitors": ["cursor"], "dimensions": None, "custom_sources": {}}
            )
        return llm_call(messages, model, **kwargs)

    return CompetitorAnalysisAPI(
        extractor=FakeExtractor(),
        llm=LLMClient(call_func=call),
        use_llm=True,
    )


class TestAnalyzeReactReport:
    def test_structured_json_into_report(self):
        # doc 49：Lead Final Answer 走 REPORT_SCHEMA（competitor + dimensions[...]）
        final = (
            'Final Answer: {"competitor": "cursor", "dimensions": [{"dimension": "pricing", '
            '"summary": "Cursor 定价已收集", "details": {"plans": 3}, "confidence": 0.8, '
            '"evidence_urls": ["https://www.cursor.com/pricing"]}]}'
        )
        report = _api(_plan_first(final)).analyze_react_report("分析 Cursor")
        assert report.competitor.name == "cursor"
        assert len(report.dimension_results) == 1
        dr = report.dimension_results[0]
        assert dr.dimension == "pricing"
        assert dr.confidence == 0.8
        assert dr.status == ResultStatus.COMPLETE
        assert dr.details["plans"] == 3
        assert report.terminal_state == "success"
        assert report.markdown_report

    def test_text_answer_degrades_to_react_dimension(self):
        report = _api(_plan_first("Final Answer: Cursor 定价已收集完毕")).analyze_react_report("分析 Cursor")
        dr = report.dimension_results[0]
        assert dr.dimension == "react"
        assert "定价" in dr.summary

    def test_analyze_react_records_budget_steps(self):
        api = _api(_plan_first("Final Answer: 结论"))
        before = api._budget.iteration_count
        api.analyze_react("分析 Cursor")
        assert api._budget.iteration_count == before + 1

    def test_analyze_react_returns_text(self):
        # analyze_react（裸字符串入口）保持向后兼容
        assert "定价" in _api(_plan_first("Final Answer: 定价已收集")).analyze_react("分析 Cursor")
