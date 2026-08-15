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
from competitor_agent.mcp_server.tools import TOOLS, TOOL_SPECS


def build_react_dispatcher(
    *,
    config: AppConfig | None = None,
    web_extract: Callable[..., str] | None = None,
) -> ToolDispatcher:
    """把 MCP 工具集（TOOLS + TOOL_SPECS）注册进 ToolDispatcher。

    - 默认全部工具走 ``mcp_server.tools`` 实现；
    - ``web_extract`` 非 None 时覆盖为该实现（facade 传 ``_react_web_extract``）；
    - 默认超时读 ``config.collector.timeout_seconds``（未给 config 则尝试 load_config）。
    """
    if config is None:
        from competitor_agent.config.loader import load_config

        config = load_config()
    dispatcher = ToolDispatcher(default_timeout=config.collector.timeout_seconds)
    for name, spec in TOOL_SPECS.items():
        func = web_extract if name == "web_extract" and web_extract is not None else TOOLS[name]
        dispatcher.register(name, func, spec=spec)
    return dispatcher
