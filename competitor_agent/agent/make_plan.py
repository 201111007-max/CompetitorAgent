"""make_plan 工具（设计文档 49 §3.5）— Lead Agent 首步强制的规划工具

Lead 第一步必须调用 make_plan 输出 PLAN_SCHEMA JSON（competitor/competitors/
dimensions/budget/custom_sources/resolution/scheduling）。本工具校验合法后原样回传
JSON——ReactLoop 的 plan 接收器
（``_on_plan``）把它解析为 ``loop.plan``，供报告组装与记忆写侧使用；
无效/未产出 plan → loop.plan 保持 None，报告侧按 partial 处理。
"""
from __future__ import annotations

import json
from typing import Any, Callable

from competitor_agent.agent.react_schemas import PLAN_SCHEMA
from competitor_agent.llm.client import LLMClient


def make_plan(plan_json: Any) -> str:
    """校验并规范化 PLAN_SCHEMA 规划 JSON；非法返回可读错误（回灌自恢复）。"""
    plan: Any = plan_json
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except (json.JSONDecodeError, TypeError):
            return "make_plan 参数解析失败：plan_json 须是合法 JSON 对象"
    if not isinstance(plan, dict):
        return "make_plan 参数解析失败：期望 JSON 对象"
    # 设计文档 62 §3.1：competitor（单竞品 registry）XOR competitors（多竞品 compare/discovery）；
    # discovery 在候选枚举前无已知竞品，允许仅带 resolution=discovery 的计划（候选后经 web_tool 枚举）。
    competitor = str(plan.get("competitor") or "").strip()
    competitors = plan.get("competitors")
    if competitors is not None and not isinstance(competitors, list):
        return "make_plan 校验失败：competitors 必须是数组（竞品规范名列表）"
    competitors = [str(c) for c in competitors] if competitors else []
    if not competitor and not competitors:
        resolution = str(plan.get("resolution") or "").strip()
        if resolution != "discovery":
            return "make_plan 校验失败：缺少必填字段 competitor（单竞品规范名）或 competitors（多竞品清单/发现后回填）"
    if competitor and competitors:
        return "make_plan 校验失败：competitor 与 competitors 不能同时出现——单竞品用 competitor，多竞品用 competitors"
    problems = LLMClient._validate_schema(plan, PLAN_SCHEMA)
    if problems:
        return f"make_plan 校验失败: {'；'.join(problems)}"
    return json.dumps(plan, ensure_ascii=False)


def build_make_plan_tool(plan_sink: Callable[[str], None] | None = None) -> Callable[..., str]:
    """构造 make_plan 工具函数（可选 plan_sink 透传；缺省由 ReactLoop 内部接收）。"""
    def _tool(plan_json: Any) -> str:
        result = make_plan(plan_json)
        if plan_sink is not None and not result.startswith("make_plan"):
            plan_sink(result)
        return result

    return _tool
