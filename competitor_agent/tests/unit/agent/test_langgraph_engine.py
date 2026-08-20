"""LangGraph 引擎单测（设计文档 51 §3.3）

图拓扑编译 / plan→delegate→report 走通（mock LLM 复用 BenchmarkMockLLM，
消息形状与自研 ReAct 路径一致故脚本原样命中）/ transcript 同构断言 /
事件序列断言 / 子 Agent 失败逐维度标注。

langgraph 为 optional extra：未安装环境整体 skip（CI 默认不装，extras 任务覆盖）。
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("langgraph", reason="langgraph 为 optional extra（pip install -e \".[langgraph]\"）")

from competitor_agent.agent.langgraph_engine import run_langgraph
from competitor_agent.agent.langgraph_engine.graph import build_graph
from competitor_agent.agent.make_plan import build_make_plan_tool
from competitor_agent.agent.prompts.react_system import build_lead_system_prompt
from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.agent.subagent_registry import build_subagent, get_subagent_registry
from competitor_agent.agent.tool_registry import build_react_dispatcher
from competitor_agent.evaluation.benchmark import BenchmarkMockLLM
from competitor_agent.llm.client import LLMClient
from competitor_agent.tests.conftest import CURSOR_PRICING


def _fake_web_extract(url: str) -> str:
    if "pricing" in url:
        return CURSOR_PRICING
    return "Cursor supports MCP integration, agent mode, and Codex-style reviews."


def _mock_llm() -> LLMClient:
    return LLMClient(call_func=BenchmarkMockLLM().complete)


def _subagent_run(llm: LLMClient):
    def run(name: str, sub_task: str):
        return build_subagent(
            name, llm, web_extract=_fake_web_extract, max_steps=4
        ).run_subagent(sub_task)

    return run


def _lead_system_prompt(llm: LLMClient) -> str:
    """与 facade 同路径构建 Lead 系统提示（工具描述 + Thought/Action 格式 + skills）。"""
    dispatcher = build_react_dispatcher(
        web_extract=_fake_web_extract,
        exclude=("analyze_competitor",),
        extra_tools={"make_plan": build_make_plan_tool()},
    )
    return ReactAgent(llm=llm, dispatcher=dispatcher).build_system_prompt(
        instructions=build_lead_system_prompt()
    )


def _run(task: str = "分析 Cursor", event_sink=None):
    llm = _mock_llm()
    return run_langgraph(
        task,
        llm=llm,
        make_plan_fn=build_make_plan_tool(),
        subagent_run=_subagent_run(llm),
        registry=get_subagent_registry(),
        event_sink=event_sink,
        system_prompt=_lead_system_prompt(llm),
    )


def test_graph_topology_compiles():
    llm = _mock_llm()
    graph = build_graph(
        llm=llm,
        make_plan_fn=build_make_plan_tool(),
        subagent_run=_subagent_run(llm),
        registry=get_subagent_registry(),
        system_prompt="",
    )
    node_names = set(graph.get_graph().nodes)
    assert {"plan", "subagent", "aggregate", "report"} <= node_names


def test_run_langgraph_plan_delegate_report():
    plan, answer, _transcript = _run()

    assert plan is not None and plan["competitor"] == "cursor"
    payload = json.loads(answer)
    assert payload["competitor"] == "cursor"
    dims = {d["dimension"] for d in payload["dimensions"]}
    assert {"pricing", "feature", "performance", "ecosystem", "sentiment", "roadmap"} == dims
    pricing = next(d for d in payload["dimensions"] if d["dimension"] == "pricing")
    assert pricing["details"]["plans"], "pricing 维度应抽取到定价条目"


def test_transcript_shape_isomorphic():
    _plan, _answer, transcript = _run()

    assert transcript, "transcript 不应为空"
    for record in transcript:
        assert {"tool", "args", "result_brief", "url"} <= set(record), record
    tools = [r["tool"] for r in transcript]
    assert tools[0] == "make_plan"
    assert "delegate" in tools
    assert tools[-1] == "report"
    assert tools.count("web_extract") >= 6  # 每维子 Agent 至少一次抓取


def test_event_sequence():
    events = []
    _run(event_sink=events.append)

    kinds = [(e.event, e.phase) for e in events]
    assert ("phase_start", "langgraph") in kinds
    assert ("phase_complete", "langgraph") in kinds
    # 子 Agent 节点事件（每维 start/complete）
    starts = [e for e in events if e.event == "phase_start" and "子 Agent 开始" in e.message]
    completes = [e for e in events if e.event == "phase_complete" and "子 Agent 完成" in e.message]
    assert len(starts) == 6 and len(completes) == 6


def test_subagent_failure_marked_not_fatal():
    llm = _mock_llm()

    def run(name: str, sub_task: str):
        if name == "pricing":
            raise RuntimeError("boom")
        return build_subagent(
            name, llm, web_extract=_fake_web_extract, max_steps=4
        ).run_subagent(sub_task)

    plan, answer, _transcript = run_langgraph(
        "分析 Cursor",
        llm=llm,
        make_plan_fn=build_make_plan_tool(),
        subagent_run=run,
        registry=get_subagent_registry(),
        system_prompt=_lead_system_prompt(llm),
    )
    assert plan is not None
    payload = json.loads(answer)
    assert payload["dimensions"], "单个子 Agent 失败不应中断整图"


def test_plan_failure_degrades_to_partial():
    llm = LLMClient(call_func=lambda messages, model=None: "无法规划")
    plan, answer, transcript = run_langgraph(
        "分析 Cursor",
        llm=llm,
        make_plan_fn=build_make_plan_tool(),
        subagent_run=_subagent_run(llm),
        registry=get_subagent_registry(),
        system_prompt=_lead_system_prompt(llm),
    )
    assert plan is None
    assert answer == "无法规划"  # report 节点非 Final Answer 输出 → 原文兜底
    tools = [r["tool"] for r in transcript]
    assert "web_extract" not in tools  # 无 plan 不 fan-out
    assert tools[0] == "make_plan" and tools[-1] == "report"
