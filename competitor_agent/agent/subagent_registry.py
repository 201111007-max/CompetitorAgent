"""子 Agent 注册表（设计文档 49 §3.2）— 独立 LLM 子 Agent 的预注册与构建

仿 deer-flow ``CustomSubagentConfig``：每个维度子 Agent = 自己的工具子集白名单
（``tools``）+ skill 名清单（``skills``）+ 专属提示（``system_prompt``）。
子 Agent 是**独立完整 agent**（自己的 ReactAgent + ReactLoop + 独立预算），
内部同样 LLM 自主调工具、自主收尾（Final Answer = SUBAGENT_RESULT_SCHEMA JSON）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from competitor_agent.agent.react_schemas import DIMENSIONS
from competitor_agent.llm.client import LLMClient
from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.subagent_registry")

# 工具子集白名单：pricing 含定价工具，ecosystem/roadmap 含 github 系列。
# 一律排除 analyze_competitor（防递归调用 analyze()）。
_SUBAGENT_TOOLS: dict[str, list[str]] = {
    "pricing": ["web_extract", "web_search", "analyze_pricing"],
    "feature": ["web_extract", "web_search"],
    "performance": ["web_extract", "web_search"],
    "ecosystem": ["web_extract", "web_search", "github_stars", "github_releases", "github_commits"],
    "sentiment": ["web_extract", "web_search"],
    "roadmap": ["web_extract", "web_search", "github_releases", "github_commits"],
}

# skill 注入清单：维度抽取 + 事实边界 + 置信度披露
_SUBAGENT_SKILLS: dict[str, list[str]] = {
    dim: [f"{dim}_analysis", "fact_verification", "confidence_disclosure"]
    for dim in DIMENSIONS
}

_SUBAGENT_DESCRIPTIONS: dict[str, str] = {
    "pricing": "分析竞品定价：套餐档位、按量计费、月付/年付价格与成本场景估算。",
    "feature": "分析竞品核心功能矩阵与特性。",
    "performance": "分析竞品性能：榜单、延迟、胜率等基准数据。",
    "ecosystem": "分析竞品生态：MCP server 数量、IDE/插件支持、GitHub 社区活跃度。",
    "sentiment": "分析竞品口碑：正负极性、社区评价。",
    "roadmap": "分析竞品路线图与版本发布节奏。",
}


@dataclass(frozen=True)
class SubagentConfig:
    """单个维度子 Agent 的预注册配置。"""

    name: str
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    system_prompt: str = ""

    @classmethod
    def for_dimension(cls, name: str) -> SubagentConfig:
        return cls(
            name=name,
            tools=tuple(_SUBAGENT_TOOLS.get(name, [])),
            skills=tuple(_SUBAGENT_SKILLS.get(name, [])),
            system_prompt=_SUBAGENT_DESCRIPTIONS.get(name, ""),
        )


class SubagentRegistry:
    """预注册 6 维度子 Agent 配置；可按名查询/追加注册。"""

    def __init__(self) -> None:
        self._configs: dict[str, SubagentConfig] = {}
        for dim in DIMENSIONS:
            self.register(SubagentConfig.for_dimension(dim))

    def register(self, config: SubagentConfig) -> None:
        self._configs[config.name] = config

    def get(self, name: str) -> SubagentConfig | None:
        return self._configs.get(name)

    def names(self) -> list[str]:
        return list(self._configs)

    def descriptions(self) -> str:
        lines = [
            f"- {name}: {cfg.system_prompt or '（无描述）'}"
            for name, cfg in self._configs.items()
        ]
        return "\n".join(lines)


_REGISTRY: SubagentRegistry | None = None


def get_subagent_registry() -> SubagentRegistry:
    """模块级单例（懒加载 + 缓存）；显式传参时建新实例（测试用）。"""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = SubagentRegistry()
    return _REGISTRY


def build_subagent(
    name: str,
    llm: LLMClient,
    *,
    config: Any | None = None,
    web_extract: Callable[..., str] | None = None,
    extra_tools: dict[str, Callable[..., str]] | None = None,
    session_id: str | None = None,
    budget: Any | None = None,
    memory_context_fn: Callable[[str], str] | None = None,
    rag_fn: Callable[[str], str] | None = None,
    event_sink: Callable[..., None] | None = None,
    obs_max_chars: int | None = None,
    max_steps: int = 6,
    protocol: str = "native",  # 设计文档 53 Q2：子 Agent 一并覆盖（默认 native 与 Lead 对齐）
    tracer: Any = None,  # 设计文档 54：子 Agent tool.call span（透传 ToolDispatcher）
    max_history_steps: int | None = None,  # 设计文档 56 Q4：配置化注入；None 用 ReactAgent 默认
):
    """构造一个维度子 Agent（独立 ReactAgent + ReactLoop）。

    - 工具面 = ``SubagentConfig.tools`` 白名单（经 ``build_subagent_dispatcher`` 过滤，
      一律排除 analyze_competitor）；
    - system prompt = 维度任务说明 + ``<dim>_analysis`` / fact_verification /
      confidence_disclosure skills（经 ``build_subagent_system_prompt`` 注入）；
    - 独立 ReactLoop：独立预算、共享 session_id 取消、共享 memory/RAG、obs 截断。
    """
    from competitor_agent.agent.prompts.react_system import build_subagent_system_prompt
    from competitor_agent.agent.react_agent import ReactAgent
    from competitor_agent.agent.react_loop import ReactLoop
    from competitor_agent.agent.tool_registry import build_subagent_dispatcher

    if config is None:
        from competitor_agent.config.loader import load_config

        config = load_config()
    dispatcher = build_subagent_dispatcher(
        name,
        config=config,
        web_extract=web_extract,
        extra_tools=extra_tools,
        tracer=tracer,  # 设计文档 54：子 Agent tool.call span
    )
    # 设计文档 54：子 Agent LLM 复用 Lead 同实例（若其带 tracer 则有 generation span）
    agent = ReactAgent(llm=llm, dispatcher=dispatcher, protocol=protocol)
    system_prompt = build_subagent_system_prompt(name)
    return ReactLoop(
        agent,
        max_steps=max_steps,
        event_sink=event_sink,
        session_id=session_id,
        budget=budget,
        memory_context_fn=memory_context_fn,
        rag_fn=rag_fn,
        obs_max_chars=obs_max_chars,
        system_prompt_override=system_prompt,
        max_history_steps=max_history_steps,
    )
