"""工具注册表 — MCP 工具集 ↔ ReAct 统一接线（设计文档 40）

唯一工具源是 ``mcp_server.tools``（``TOOLS`` + ``TOOL_SPECS``，含设计文档 38 schema 契约）。
``build_react_dispatcher`` 把工具集注册进 ``ToolDispatcher`` 供 ReAct agent 自主调用；
``web_extract`` 可覆盖为真实采集链路实现（facade 侧传 ``_react_web_extract``，
复用真实抓取 + 设计文档 41 URL 守卫）。
"""
from __future__ import annotations

from typing import Callable

from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.config.loader import AppConfig
from competitor_agent.mcp_server.tools import TOOL_SPECS, TOOLS


def build_react_dispatcher(
    *,
    config: AppConfig | None = None,
    web_extract: Callable[..., str] | None = None,
    exclude: tuple[str, ...] = (),
    extra_tools: dict[str, Callable[..., str]] | None = None,
) -> ToolDispatcher:
    """把 MCP 工具集（TOOLS + TOOL_SPECS）注册进 ToolDispatcher。

    - 默认全部工具走 ``mcp_server.tools`` 实现；
    - ``web_extract`` 非 None 时覆盖为该实现（facade 传 ``_react_web_extract``）；
    - ``exclude``：从工具面剔除的工具名（如防递归的 ``analyze_competitor``）；
    - ``extra_tools``：追加的非 MCP 工具（Lead 编排的 make_plan/delegate/复核工具等）；
    - 默认超时读 ``config.collector.timeout_seconds``（未给 config 则尝试 load_config）。
    """
    if config is None:
        from competitor_agent.config.loader import load_config

        config = load_config()
    dispatcher = ToolDispatcher(default_timeout=config.collector.timeout_seconds)
    for name, spec in TOOL_SPECS.items():
        if name in exclude:
            continue
        func = web_extract if name == "web_extract" and web_extract is not None else TOOLS[name]
        dispatcher.register(name, func, spec=spec)
    for name, func in (extra_tools or {}).items():
        dispatcher.register(name, func)
    return dispatcher


def build_subagent_dispatcher(
    name: str,
    *,
    config: AppConfig | None = None,
    web_extract: Callable[..., str] | None = None,
    extra_tools: dict[str, Callable[..., str]] | None = None,
) -> ToolDispatcher:
    """按子 Agent 配置的工具子集白名单构造工具面（设计文档 49 §3.6）。

    子 Agent 只注册 ``SubagentConfig.tools`` 命中的工具（一律不含 analyze_competitor，
    天然防递归）；``web_extract`` 可覆盖为真实采集链路；``extra_tools`` 追加专属工具
    （如 pricing 子 Agent 的 estimate_costs）。
    """
    from competitor_agent.agent.subagent_registry import get_subagent_registry

    if config is None:
        from competitor_agent.config.loader import load_config

        config = load_config()
    cfg = get_subagent_registry().get(name)
    whitelist = set(cfg.tools) if cfg is not None else set()
    dispatcher = ToolDispatcher(default_timeout=config.collector.timeout_seconds)
    for tool_name, spec in TOOL_SPECS.items():
        if tool_name not in whitelist:
            continue
        func = web_extract if tool_name == "web_extract" and web_extract is not None else TOOLS[tool_name]
        dispatcher.register(tool_name, func, spec=spec)
    for tool_name, func in (extra_tools or {}).items():
        dispatcher.register(tool_name, func)
    return dispatcher
