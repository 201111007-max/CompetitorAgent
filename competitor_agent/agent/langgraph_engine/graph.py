"""StateGraph 组装（设计文档 51 §2.1）：plan → Send fan-out → aggregate → report

langgraph 导入局限在本模块（包外只接触 ``run_langgraph`` 签名）。
并发用 ``Send`` fan-out（LangGraph 原生 map-reduce），对齐自研
``DelegateRunner`` 的批量并发语义。
"""
from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from competitor_agent.agent.langgraph_engine import nodes
from competitor_agent.agent.langgraph_engine.state import EngineState
from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.langgraph_engine.graph")


def build_graph(
    *,
    llm: Any,
    make_plan_fn: Callable[..., str],
    subagent_run: Callable[[str, str], Any],
    registry: Any,
    event_sink: Callable | None = None,
    system_prompt: str = "",
) -> Any:
    """构建并编译引擎图，返回 CompiledGraph。"""

    def delegate_fanout(state: EngineState) -> list[Send]:
        """按 plan.dimensions fan-out（Send API），每维度一条边。

        plan 缺失/无可委派维度 → 直送 aggregate（report 节点按无结果兜底）。
        """
        plan = state.get("plan") or {}
        dims = [d for d in plan.get("dimensions") or [] if registry.get(d)]
        if not dims:
            logger.warning("plan 无可委派维度，跳过子 Agent fan-out")
            return [Send("aggregate", {"task": state["task"]})]
        return [Send("subagent", {"task": state["task"], "dimension": dim}) for dim in dims]

    builder = StateGraph(EngineState)
    builder.add_node("plan", nodes.make_plan_node(llm, make_plan_fn, system_prompt=system_prompt))
    builder.add_node("subagent", nodes.make_subagent_node(subagent_run, event_sink=event_sink))
    builder.add_node("aggregate", nodes.make_aggregate_node())
    builder.add_node("report", nodes.make_report_node(llm, system_prompt=system_prompt))
    builder.add_edge(START, "plan")
    builder.add_conditional_edges("plan", delegate_fanout, ["subagent", "aggregate"])
    builder.add_edge("subagent", "aggregate")
    builder.add_edge("aggregate", "report")
    builder.add_edge("report", END)
    return builder.compile()
