"""LangGraph 引擎状态（设计文档 51 §2.1）

``subagent_results``/``transcript`` 用 operator.add reducer：Send fan-out 的
并行子 Agent 节点并发写同一键，按 list 连接合并（错乱序由 aggregate 节点归位）。
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class EngineState(TypedDict, total=False):
    task: str
    plan: dict[str, Any] | None
    subagent_results: Annotated[list[dict[str, Any]], operator.add]
    merged_results: str
    final_answer: str
    transcript: Annotated[list[dict[str, Any]], operator.add]
