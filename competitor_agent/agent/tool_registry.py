"""工具注册表 — MCP 工具集 ↔ ReAct 统一接线（设计文档 40）

唯一工具源是 ``mcp_server.tools``（``TOOLS`` + ``TOOL_SPECS``，含设计文档 38 schema 契约）。
``build_react_dispatcher`` 把工具集注册进 ``ToolDispatcher`` 供 ReAct agent 自主调用；
``web_extract`` 可覆盖为真实采集链路实现（facade 侧传 ``_react_web_extract``，
复用真实抓取 + 设计文档 41 URL 守卫）。

设计文档 53 M1：``build_openai_tools`` 把同一 dispatcher 的工具契约转换为 OpenAI
tools 请求参数格式（原生 function calling 下发用），与文本协议的
``get_tool_descriptions`` 同源——一份契约、两种下发形态。
"""
from __future__ import annotations

import inspect
from typing import Any, Callable

from competitor_agent.agent.tool_dispatcher import ToolDispatcher, ToolSpec
from competitor_agent.config.loader import AppConfig
from competitor_agent.mcp_server.tools import TOOL_SPECS, TOOLS

# Python 注解 → JSON Schema 类型（无 schema 的 extra_tools 从签名派生最小 parameters）
_ANNOTATION_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "dict": "object",
}


def build_openai_tools(dispatcher: ToolDispatcher) -> list[dict[str, Any]]:
    """把 dispatcher 已注册工具转换为 OpenAI tools 格式（设计文档 53 M1）。

    - 有 ``params_schema`` 的 ToolSpec（MCP 工具，设计文档 38 契约）直接映射，零改动；
    - 无 schema 的 extra_tools（make_plan 等）从函数签名派生最小 parameters：
      无默认值参数进 ``required``，类型按注解映射（缺省 string）。
    """
    tools: list[dict[str, Any]] = []
    for name, spec in dispatcher.specs.items():
        params = spec.params_schema or _derive_params_schema(spec)
        function: dict[str, Any] = {"name": name, "parameters": params}
        if spec.description:
            function["description"] = spec.description
        tools.append({"type": "function", "function": function})
    return tools


def _derive_params_schema(spec: ToolSpec) -> dict[str, Any]:
    """无契约工具从函数签名派生最小 JSON Schema（required = 无默认值参数）。"""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for p in inspect.signature(spec.func).parameters.values():
        if p.name in ("self", "cls"):
            continue
        ann = p.annotation
        ptype = "string" if ann is inspect.Parameter.empty else _ANNOTATION_TYPE_MAP.get(ann, "string")
        properties[p.name] = {"type": ptype}
        if p.default is inspect.Parameter.empty:
            required.append(p.name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _register_extra_tools(
    dispatcher: ToolDispatcher,
    extra_tools: dict[str, Callable[..., str] | ToolSpec] | None,
) -> None:
    """注册 extra_tools（非 MCP 工具，设计文档 49/56）。

    值为 ``ToolSpec`` 时携带描述/schema 注册（如 kb_recall 的使用纪律描述）；
    普通 callable 沿用默认契约。
    """
    for name, tool in (extra_tools or {}).items():
        if isinstance(tool, ToolSpec):
            dispatcher.register(name, tool.func, spec=tool)
        else:
            dispatcher.register(name, tool)


def build_react_dispatcher(
    *,
    config: AppConfig | None = None,
    web_extract: Callable[..., str] | None = None,
    exclude: tuple[str, ...] = (),
    extra_tools: dict[str, Callable[..., str] | ToolSpec] | None = None,
    tracer: Any = None,  # 设计文档 54：tool.call span
) -> ToolDispatcher:
    """把 MCP 工具集（TOOLS + TOOL_SPECS）注册进 ToolDispatcher。

    - 默认全部工具走 ``mcp_server.tools`` 实现；
    - ``web_extract`` 非 None 时覆盖为该实现（facade 传 ``_react_web_extract``）；
    - ``exclude``：从工具面剔除的工具名（如防递归的 ``analyze_competitor``）；
    - ``extra_tools``：追加的非 MCP 工具（Lead 编排的 make_plan/delegate/复核工具、
      设计文档 56 的 kb_recall 等）；值为 ToolSpec 时携带描述/schema 注册；
    - 默认超时读 ``config.collector.timeout_seconds``（未给 config 则尝试 load_config）。
    """
    if config is None:
        from competitor_agent.config.loader import load_config

        config = load_config()
    dispatcher = ToolDispatcher(default_timeout=config.collector.timeout_seconds, tracer=tracer)
    for name, spec in TOOL_SPECS.items():
        if name in exclude:
            continue
        func = web_extract if name == "web_extract" and web_extract is not None else TOOLS[name]
        dispatcher.register(name, func, spec=spec)
    _register_extra_tools(dispatcher, extra_tools)
    return dispatcher


def build_subagent_dispatcher(
    name: str,
    *,
    config: AppConfig | None = None,
    web_extract: Callable[..., str] | None = None,
    extra_tools: dict[str, Callable[..., str] | ToolSpec] | None = None,
    tracer: Any = None,  # 设计文档 54：子 Agent 的 tool.call span
) -> ToolDispatcher:
    """按子 Agent 配置的工具子集白名单构造工具面（设计文档 49 §3.6 / 62 §3.2）。

    子 Agent 只注册 ``SubagentConfig.tools`` 命中的工具（一律不含 analyze_competitor，
    天然防递归）；候选竞品名经 ``resolve`` 落到 competitor 配置（设计文档 62 §3.2）；
    ``web_extract`` 可覆盖为真实采集链路；``extra_tools`` 追加专属工具。
    """
    from competitor_agent.agent.subagent_registry import get_subagent_registry

    if config is None:
        from competitor_agent.config.loader import load_config

        config = load_config()
    cfg = get_subagent_registry().resolve(name)
    whitelist = set(cfg.tools) if cfg is not None else set()
    dispatcher = ToolDispatcher(default_timeout=config.collector.timeout_seconds, tracer=tracer)
    for tool_name, spec in TOOL_SPECS.items():
        if tool_name not in whitelist:
            continue
        func = web_extract if tool_name == "web_extract" and web_extract is not None else TOOLS[tool_name]
        dispatcher.register(tool_name, func, spec=spec)
    _register_extra_tools(dispatcher, extra_tools)
    return dispatcher
