"""run_langgraph — LangGraph 引擎入口（设计文档 51 §2.2）

返回与自研 ReAct 路径同形的 ``(plan, answer, transcript)`` 三元组，
使 assemble / 记忆写侧 / 归档 / 导出 / 时间线全部复用。

记忆/RAG 召回文本在图运行前解析一次，注入 plan/report 节点系统提示——
与自研路径「plan 节点前注入同样文本」一致。
"""
from __future__ import annotations

from typing import Any, Callable

from competitor_agent.agent.prompts.react_system import enrich_prompt
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.langgraph_engine")


def run_langgraph(
    task: str,
    *,
    llm: Any,
    make_plan_fn: Callable[..., str],
    subagent_run: Callable[[str, str], Any],
    registry: Any,
    event_sink: Callable[[ProgressEvent], None] | None = None,
    session_id: str | None = None,
    memory_ctx_fn: Callable[[str], str] | None = None,
    rag_fn: Callable[[str], str] | None = None,
    system_prompt: str = "",
) -> tuple[dict | None, str, list[dict]]:
    """跑一遍 LangGraph 编排引擎，返回 (plan, final_answer, transcript)。

    取消/预算/checkpoint 不对齐（设计文档 51 §1.2）：图级无中断与恢复，
    作为双引擎对照的差异化结论呈现；``session_id`` 仅透传给子 Agent 运行时。
    """
    from competitor_agent.agent.langgraph_engine.graph import build_graph

    prompt = _enriched_system_prompt(system_prompt, task, memory_ctx_fn, rag_fn)
    graph = build_graph(
        llm=llm,
        make_plan_fn=make_plan_fn,
        subagent_run=subagent_run,
        registry=registry,
        event_sink=event_sink,
        system_prompt=prompt,
    )
    _emit(event_sink, ProgressEvent(event="phase_start", phase="langgraph", message="LangGraph 引擎启动"))
    final = graph.invoke({"task": task, "subagent_results": [], "transcript": []})
    _emit(event_sink, ProgressEvent(event="phase_complete", phase="langgraph", message="LangGraph 引擎完成"))
    return (
        final.get("plan"),
        str(final.get("final_answer") or ""),
        list(final.get("transcript") or []),
    )


def _enriched_system_prompt(
    base: str,
    task: str,
    memory_ctx_fn: Callable[[str], str] | None,
    rag_fn: Callable[[str], str] | None,
) -> str:
    """记忆/RAG 召回注入系统提示（与 ReactLoop 同文本，失败静默降级）。"""
    notes = [ctx] if (ctx := _resolve(memory_ctx_fn, task)) else None
    knowledge = [ctx] if (ctx := _resolve(rag_fn, task)) else None
    if not notes and not knowledge:
        return base
    return enrich_prompt(base, notes=notes, knowledge=knowledge)


def _resolve(fn: Callable[[str], str] | None, task: str) -> str:
    if fn is None:
        return ""
    try:
        return fn(task) or ""
    except Exception:
        logger.warning("LangGraph 引擎记忆/RAG 召回失败", exc_info=True)
        return ""


def _emit(event_sink: Callable[[ProgressEvent], None] | None, event: ProgressEvent) -> None:
    if event_sink is not None:
        event_sink(event)
