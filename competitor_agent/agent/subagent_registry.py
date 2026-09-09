"""子 Agent 注册表（设计文档 49 §3.2）— 独立 LLM 子 Agent 的预注册与构建

仿 deer-flow ``CustomSubagentConfig``：每个维度子 Agent = 自己的工具子集白名单
（``tools``）+ skill 名清单（``skills``）+ 专属提示（``system_prompt``）。
子 Agent 是**独立完整 agent**（自己的 ReactAgent + ReactLoop + 独立预算），
内部同样 LLM 自主调工具、自主收尾（Final Answer = SUBAGENT_RESULT_SCHEMA JSON）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from competitor_agent.agent.react_loop import ReactLoop
from competitor_agent.agent.subagent_registry_defaults import (
    _SUBAGENT_DESCRIPTIONS,
    _SUBAGENT_SKILLS,
    _SUBAGENT_TOOLS,
    CODING_DIMENSIONS,
)
from competitor_agent.agent.tool_dispatcher import ToolSpec
from competitor_agent.llm.client import LLMClient
from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.subagent_registry")

# 候选竞品子 Agent（设计文档 62 §3.2）：整竞品分析，工具面排除 delegate 防递归。
_COMPETITOR_TOOLS = (
    "web_extract",
    "web_search",
    "github_stars",
    "github_releases",
    "github_commits",
    "analyze_pricing",
)
_COMPETITOR_SKILLS = ("fact_verification", "confidence_disclosure")
_COMPETITOR_DESCRIPTION = (
    "分析候选竞品全貌：定价/功能/性能/生态/口碑/路线图，"
    "输出整竞品结论与核实到的官方来源。"
)
_COMPETITOR_NAME = "competitor"


@dataclass(frozen=True)
class SubagentConfig:
    """单个维度子 Agent 的预注册配置。"""

    name: str
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    system_prompt: str = ""
    data_sources: tuple[dict[str, str], ...] = ()  # 设计文档 79：pack 声明式数据源

    @classmethod
    def for_dimension(cls, name: str) -> SubagentConfig:
        """内联 coding 默认（设计文档 79 兜底层；优先走 from_pack）。"""
        pack = CODING_DIMENSIONS
        spec = pack.dimension(name)
        return cls(
            name=name,
            tools=spec.tools if spec else tuple(_SUBAGENT_TOOLS.get(name, [])),
            skills=spec.skills if spec else tuple(_SUBAGENT_SKILLS.get(name, [])),
            system_prompt=spec.description if spec else _SUBAGENT_DESCRIPTIONS.get(name, ""),
            data_sources=spec.data_sources if spec else (),
        )

    @classmethod
    def for_competitor(cls) -> SubagentConfig:
        """候选竞品子 Agent 的通用配置（设计文档 62 §3.2，独立命名空间）。"""
        return cls(
            name=_COMPETITOR_NAME,
            tools=tuple(_COMPETITOR_TOOLS),
            skills=tuple(_COMPETITOR_SKILLS),
            system_prompt=_COMPETITOR_DESCRIPTION,
        )


class SubagentRegistry:
    """预注册维度 + 1 通用 candidate 命名空间子 Agent 配置；可按名查询/追加注册。

    设计文档 62 §3.2：注册表是唯一委派键源——维度名 → 维度配置；其他任意名
    （候选竞品）经 ``resolve`` 落到 ``competitor`` 通用配置，无需逐个登记即可委派。
    设计文档 79 §2.2（L1）：维度配置来自激活 DomainPack（``from_pack``）。
    """

    def __init__(self) -> None:
        self._configs: dict[str, SubagentConfig] = {}
        from competitor_agent.agent.react_schemas import DIMENSIONS

        for dim in DIMENSIONS:
            self.register(SubagentConfig.for_dimension(dim))
        self.register(SubagentConfig.for_competitor())

    @classmethod
    def from_pack(cls, pack: Any) -> SubagentRegistry:
        """按 DomainPack 构建注册表（L1 下沉）：维度定义 = pack.dimensions。"""
        registry = cls.__new__(cls)
        registry._configs = {}
        for spec in pack.dimensions:
            registry.register(
                SubagentConfig(
                    name=spec.name,
                    tools=tuple(spec.tools),
                    skills=tuple(spec.skills),
                    system_prompt=spec.description,
                    data_sources=tuple(spec.data_sources),
                )
            )
        registry.register(SubagentConfig.for_competitor())
        return registry

    def register(self, config: SubagentConfig) -> None:
        self._configs[config.name] = config

    def get(self, name: str) -> SubagentConfig | None:
        return self._configs.get(name)

    def resolve(self, name: str) -> SubagentConfig | None:
        """把委派目标名解析为子 Agent 配置（候选竞品名回退到 competitor 命名空间）。"""
        return self._configs.get(name) or self._configs.get(_COMPETITOR_NAME)

    def names(self) -> list[str]:
        return list(self._configs)

    def descriptions(self) -> str:
        lines = [
            f"- {name}: {cfg.system_prompt or '（无描述）'}"
            for name, cfg in self._configs.items()
        ]
        return "\n".join(lines)


# pack 名 → 注册表缓存（设计文档 79：按激活 pack 构建；env/config 切换后重建）
_REGISTRY_BY_PACK: dict[str, SubagentRegistry] = {}


def reset_subagent_registry() -> None:
    """清空缓存（测试/运行时切 pack 后调用，下次 get 重建）。"""
    _REGISTRY_BY_PACK.clear()


def get_subagent_registry() -> SubagentRegistry:
    """按激活 DomainPack 构建的模块级缓存单例（设计文档 79 §2.2 L1）。

    pack 加载失败 → 回退内联 coding 默认（SubagentRegistry() 现状等价）。
    """
    from competitor_agent.core.domain_pack import active_domain_pack, active_pack_name

    name = active_pack_name()
    cached = _REGISTRY_BY_PACK.get(name)
    if cached is not None:
        return cached
    try:
        pack = active_domain_pack()
        registry = SubagentRegistry.from_pack(pack)
    except Exception:
        logger.warning("DomainPack 子 Agent 注册表构建失败，回退内联默认", exc_info=True)
        registry = SubagentRegistry()
    _REGISTRY_BY_PACK[name] = registry
    return registry


def build_subagent(
    name: str,
    llm: LLMClient,
    *,
    config: Any | None = None,
    web_extract: Callable[..., str] | None = None,
    extra_tools: dict[str, Callable[..., str] | ToolSpec] | None = None,
    session_id: str | None = None,
    budget: Any | None = None,
    memory_context_fn: Callable[[str], str] | None = None,
    rag_fn: Callable[[str], str] | None = None,
    event_sink: Callable[..., None] | None = None,
    obs_max_chars: int | None = None,
    max_steps: int | None = None,
    tracer: Any = None,  # 设计文档 54：子 Agent tool.call span（透传 ToolDispatcher）
    max_history_steps: int | None = None,  # 设计文档 56 Q4：配置化注入；None 用 ReactAgent 默认
    max_parallel_tool_calls: int = 4,  # 设计文档 59：单回合多 tool_calls 并发上限；1 = 串行
) -> ReactLoop:
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
    agent = ReactAgent(
        llm=llm, dispatcher=dispatcher, max_parallel_tool_calls=max_parallel_tool_calls
    )
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
