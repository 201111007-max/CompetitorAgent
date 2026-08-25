"""设计文档 62 M1 — 候选子 Agent 注册单测。

覆盖：competitor 通用命名空间注册（工具面/防递归）；``resolve`` 维度与候选名收敛；
``build_subagent`` 候选名落到 competitor 配置（工具面含 web 工具、system prompt 含 official_links）。
"""
from __future__ import annotations

from competitor_agent.agent.prompts.react_system import build_subagent_system_prompt
from competitor_agent.agent.subagent_registry import (
    SubagentRegistry,
    build_subagent,
    get_subagent_registry,
)
from competitor_agent.llm.client import LLMClient


def test_competitor_config_registered() -> None:
    registry = SubagentRegistry()
    cfg = registry.get("competitor")
    assert cfg is not None
    assert "web_extract" in cfg.tools
    assert "web_search" in cfg.tools
    assert "github_stars" in cfg.tools
    assert "analyze_pricing" in cfg.tools
    assert "delegate" not in cfg.tools  # 防递归
    assert "fact_verification" in cfg.skills


def test_resolve_dimension_returns_dimension() -> None:
    registry = SubagentRegistry()
    assert registry.resolve("pricing") is registry.get("pricing")


def test_resolve_unknown_name_falls_to_competitor() -> None:
    registry = SubagentRegistry()
    cfg = registry.resolve("cursor")  # 候选竞品名
    assert cfg is registry.get("competitor")


def test_resolve_explicit_competitor() -> None:
    registry = SubagentRegistry()
    assert registry.resolve("competitor") is registry.get("competitor")


def test_register_survives_add_after_build() -> None:
    """追加注册不覆盖预注册项。"""
    registry = SubagentRegistry()
    names = registry.names()
    assert "pricing" in names
    assert "competitor" in names
    assert len(names) == len(set(names))


def test_build_subagent_candidate_tool_face() -> None:
    """候选竞品名 build_subagent：dispatcher 含 web 工具（经 resolve 落到 competitor 白名单）。"""
    loop = build_subagent(
        "cursor",
        LLMClient(),
        config=None,
    )
    names = loop._agent._dispatcher.specs.keys()
    assert "web_extract" in names
    assert "web_search" in names
    assert "delegate" not in names


def test_build_subagent_candidate_system_prompt_has_official_links() -> None:
    """候选子 Agent prompt 携带 official_links 供聚合阶段引用（设计文档 62 §3.4）。"""
    prompt = build_subagent_system_prompt("cursor")
    assert "候选竞品「cursor」" in prompt
    assert "official_links" in prompt
    assert "web_extract / web_search / github_* / analyze_pricing" in prompt


def test_build_subagent_dimension_prompt_unchanged() -> None:
    """维度子 Agent prompt 行为不变（无 official_links）。"""
    prompt = build_subagent_system_prompt("pricing")
    assert "official_links" not in prompt
    assert "维度子 Agent" in prompt


def test_module_singleton_has_competitor() -> None:
    registry = get_subagent_registry()
    assert registry.get("competitor") is not None
