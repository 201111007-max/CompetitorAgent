"""依赖装配（设计文档 78 §2.1）：``build_dependencies`` 产出 ``Dependencies`` 只读快照。

拆分规则（doc 78 §2.2）：
- 循环依赖防护：本模块不 import 任何 service；services 不 import api——
  跨服务调用一律经 ``host``（门面实例）路由，由门面统一编排。
- ``ServiceBase`` 把依赖快照按原私有名展开到服务实例（``_config``/``_llm``/…），
  使迁移的方法体逐位复用；``_emit`` 为共享事件出口。
- 日志命名空间保持 ``competitor_agent.facade.api``（装配期"向量层状态"等启动
  日志与既有 caplog 断言/运维面板兼容，见 doc 78 迁移表）。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

from competitor_agent.collector.web_extractor import WebExtractor
from competitor_agent.config.loader import AppConfig, load_config
from competitor_agent.core.approval_gate import ApprovalPolicy
from competitor_agent.core.budget_controller import BudgetController
from competitor_agent.core.competitor_discoverer import CompetitorDiscoverer
from competitor_agent.core.domain_pack import DomainPack, active_domain_pack
from competitor_agent.core.report_builder import ReportBuilder
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.interfaces.memory import IFourLayerMemory

# 设计文档 93 §2.3：knowledge_base↔memory 循环依赖已拆解（tokenize 下沉
# domain_types.text_utils），恢复顶层导入。CompetitorStore 经模块属性实例化
# （保持测试可 monkeypatch 其宿主模块）。
from competitor_agent.knowledge_base import competitor_store as _competitor_store_mod
from competitor_agent.knowledge_base.competitor_store import CompetitorStore
from competitor_agent.knowledge_base.ingester import Ingester
from competitor_agent.knowledge_base.reranker import CrossEncoderReranker
from competitor_agent.knowledge_base.retriever import Retriever
from competitor_agent.knowledge_base.vector_store import VectorStore
from competitor_agent.llm.client import LLMClient
from competitor_agent.memory.four_layer_memory import FourLayerMemory
from competitor_agent.memory.timeline_memory import TimelineMemory

logger = logging.getLogger("competitor_agent.facade.api")


@dataclass(frozen=True)
class Dependencies:
    """门面依赖只读快照（doc 78 §2.2 规则 2）：四服务构造时注入，字段即原 ``self._*``。"""

    engine: str
    config: AppConfig
    llm: LLMClient | None
    use_llm: bool
    event_sink: Callable[[ProgressEvent], None] | None
    stream_sink: Callable[[Any], None] | None
    memory: IFourLayerMemory | None
    tool_dispatcher: object | None
    max_parallel_tool_calls: int
    extractor: WebExtractor
    domain_pack: DomainPack
    builder: ReportBuilder
    budget: BudgetController
    timeline: TimelineMemory
    approval_enabled: bool
    approval_policy: ApprovalPolicy
    store: CompetitorStore | None
    ingester: Ingester | None
    retriever: Retriever | None
    vector_store: VectorStore | None
    reranker: CrossEncoderReranker | None
    discoverer: CompetitorDiscoverer
    tracer: Any


# 依赖 → 私有属性名映射（``_name``），服务与门面共用同一展开逻辑
_DEP_FIELDS: tuple[str, ...] = tuple(Dependencies.__dataclass_fields__)


def install_deps(deps: Dependencies, target: object) -> None:
    """把依赖快照按原私有名展开到实例（门面与服务共用，保证对象身份共享）。"""
    for name in _DEP_FIELDS:
        setattr(target, f"_{name}", getattr(deps, name))


def build_dependencies(
    llm: LLMClient | None = None,
    use_llm: bool = True,
    max_iterations: int | None = None,
    event_sink: Callable[[ProgressEvent], None] | None = None,
    stream_sink: Callable[[Any], None] | None = None,  # 设计文档 63 §5.5：仅 Lead 流式旁路（默认关闭）
    extractor: WebExtractor | None = None,
    memory: IFourLayerMemory | None = None,
    config: AppConfig | None = None,
    web_tool: Callable[[str], list[dict]] | None = None,
    timeline: TimelineMemory | None = None,
    enable_rag: bool = True,  # 设计文档 30：消融开关（默认开启，行为不变）
    enable_memory: bool = True,  # 设计文档 30：消融开关（默认开启，行为不变）
    rag_store: CompetitorStore | None = None,  # 设计文档 30：消融可注入共享知识库实例
    vector_store: VectorStore | None = None,  # 设计文档 32：可注入向量层（测试/评测确定性 mock）
    reranker: CrossEncoderReranker | None = None,  # 设计文档 93：可注入精排层（None 时默认探测构造）
    tool_dispatcher: object | None = None,  # 历史兼容：已由 Lead 工具面取代，保留签名
    engine: str = "react",  # 设计文档 51：编排引擎 "react"（默认）| "langgraph"
    tracer: Any = None,  # 设计文档 54：链路追踪底座（None 用模块单例，默认 JsonlSink）
    max_parallel_tool_calls: int = 4,  # 设计文档 59：单回合多 tool_calls 并发上限；1 = 串行
) -> Dependencies:
    """装配全部依赖（原 ``CompetitorAnalysisAPI.__init__`` 装配体逐位迁移）。"""
    # 配置注入：显式参数优先，其次 config，最后默认值
    cfg = config or load_config()
    if engine not in ("react", "langgraph"):
        raise ValueError(f"未知编排引擎: {engine!r}（可用: react | langgraph）")
    if engine == "langgraph":
        # 构造期检查（设计文档 51 §2.2）：未装 langgraph → 可读 ImportError
        from competitor_agent.agent.langgraph_engine import ensure_langgraph_available

        ensure_langgraph_available()
    max_iterations = max_iterations if max_iterations is not None else cfg.budget.max_iterations
    # enable_memory=False：门控全部记忆副作用（set_success_rates / _apply_memory_boost /
    # record_skill / record_outcome / archive_session），下游均判 `memory is None`
    mem = memory if enable_memory else None

    extractor_out = extractor or WebExtractor()
    # DomainPack（设计文档 79）：激活领域包——维度/权重/品类随 pack 注入装配层
    domain_pack = active_domain_pack(cfg)
    # 新鲜度 TTL（设计文档 26）：build() 为报告计算 freshness 元数据
    builder = ReportBuilder(
        dimension_ttl_days=cfg.freshness.dimension_ttl_days,
        dimension_weights=domain_pack.default_dimension_weights or None,
    )
    budget = BudgetController(max_iterations=max_iterations)
    # 竞品时间线记忆（设计文档 26 §3.4）：跨分析 diff，独立于四层记忆
    timeline_out = timeline or TimelineMemory()
    # human-in-the-loop 审批门（设计文档 67 §3.2）：触发规则 → 报告 JSON 标 pending_review
    approval_enabled = bool(cfg.report.approval_enabled)
    approval_policy = ApprovalPolicy(
        low_confidence_threshold=cfg.report.approval_low_confidence_threshold
    )

    # RAG 知识库：分析后摄入 + Lead/子 Agent 检索注入（外部事实依据，降低幻觉）
    # enable_rag=False：不组装知识库，Lead/子 Agent 对 None 走"跳过检索"路径
    # （设计文档 93 §2.3：knowledge_base↔memory 循环依赖已拆解，恢复顶层导入与类型契约）
    store: CompetitorStore | None = None
    ingester: Ingester | None = None
    retriever: Retriever | None = None
    vector_store_out: VectorStore | None = None
    reranker_out: CrossEncoderReranker | None = None
    if enable_rag:
        # 向量层（设计文档 32）：注入的优先；默认 VectorStore 懒加载——嵌入模型
        # 不可用（未缓存/未装依赖）时 is_available()=False，检索自动降级纯词袋，行为不变
        if vector_store is not None:
            vector_store_out = vector_store
        else:
            vector_store_out = VectorStore()
        store = rag_store or _competitor_store_mod.CompetitorStore(
            vector_store=vector_store_out
        )
        ingester = Ingester(store=store)
        # 精排层（设计文档 93 §2.2，决策 5/6）：注入的优先；默认本地权重探测
        # （不触网），权重未缓存 → None，检索完全走现状 hybrid 路径（回归安全阀）
        if reranker is not None:
            reranker_out = reranker
        else:
            candidate = CrossEncoderReranker()
            reranker_out = candidate if candidate.is_available() else None
        retriever = Retriever(store=store, reranker=reranker_out)

        # 记忆召回向量层（设计文档 52 §2.1）：独立 collection 与知识库隔离，
        # 注入 L1 会话归档；嵌入模型不可用/未装 rag extra 时 is_available()=False，
        # 记忆召回保持词袋路径，行为与现状逐位一致
        if isinstance(mem, FourLayerMemory):
            mem.attach_vector_store(
                VectorStore(collection_name="session_summaries", data_dir=mem.data_dir)
            )

        # 启动状态日志（设计文档 52 §2.2）：消除静默降级
        vs = vector_store_out
        if vs.is_available():
            logger.info("向量层状态: available(%s)", vs.model_name)
        else:
            logger.info("向量层状态: degraded(模型 %s 未缓存，降级词袋)", vs.model_name)
        if reranker_out is not None:
            logger.info("精排层状态: available(%s)", reranker_out.model_name)
        else:
            logger.info("精排层状态: degraded(权重未缓存，hybrid 结果直出)")
    else:
        store = None
        ingester = None
        retriever = None
        vector_store_out = None
        reranker_out = None

    # 竞品发现器（设计文档 20）：仅 DISCOVERY 意图时被调用，web_tool 可注入。
    # 设计文档 66 §3.1 + 71 §2.2：未显式注入 web_tool 时，装配层零入口注入搜索路由
    # （build_search_router——DDG 免费主力恒可用，Tavily 配 Key 才注册为增强降级；
    # enable_external_sources 主开关门控。无 provider → 保持 None 空候选降级，不编造）。
    # Web/CLI/MCP 三入口都经本构造，自动受益。
    search_web_tool = web_tool
    if (
        search_web_tool is None
        and use_llm
        and llm is not None
        and cfg.collector.enable_external_sources
    ):
        from competitor_agent.collector.search import (
            build_search_router,
            web_search_candidates,
        )

        search_provider = build_search_router(cfg.collector)
        if search_provider is not None:
            search_web_tool = lambda task: web_search_candidates(
                task,
                search_provider,
                llm,
                max_results=cfg.collector.search_max_results,
            )
    discoverer = CompetitorDiscoverer(
        llm=llm, use_llm=use_llm, web_tool=search_web_tool
    )

    # 设计文档 54：链路追踪底座。显式注入优先（测试隔离）；否则模块单例。
    # 可选 Langfuse exporter：ObservabilityConfig.langfuse_enabled 派生属性为真时才
    # 追加（宿主/公钥/密钥三环境变量齐全 + SDK 可导入），否则纯本地 JsonlSink。
    from competitor_agent.observability.langfuse_exporter import LangfuseExporter
    from competitor_agent.observability.tracer import JsonlSink, Tracer, get_tracer

    if tracer is not None:
        tracer_out: Any = tracer
    elif cfg.observability.langfuse_enabled:
        tracer_out = Tracer(sinks=[JsonlSink(), LangfuseExporter()])
    else:
        tracer_out = get_tracer()

    return Dependencies(
        engine=engine,
        config=cfg,
        llm=llm,
        use_llm=use_llm,
        event_sink=event_sink,
        stream_sink=stream_sink,
        memory=mem,
        tool_dispatcher=tool_dispatcher,
        max_parallel_tool_calls=max_parallel_tool_calls,
        extractor=extractor_out,
        domain_pack=domain_pack,
        builder=builder,
        budget=budget,
        timeline=timeline_out,
        approval_enabled=approval_enabled,
        approval_policy=approval_policy,
        store=store,
        ingester=ingester,
        retriever=retriever,
        vector_store=vector_store_out,
        reranker=reranker_out,
        discoverer=discoverer,
        tracer=tracer_out,
    )


class ServiceBase:
    """四服务共享基类：依赖快照按原私有名展开 + 跨服务能力经 host（门面）路由。

    - ``_emit``：共享事件出口（原 ``CompetitorAnalysisAPI._emit`` 语义逐位一致）；
    - ``_default_llm``/``_memory_ctx_for``：懒构造 LLM 与记忆召回的唯一实现留在门面
      （懒缓存单点 + 测试实例级 patch 兼容），服务经 host 委派调用。
    """

    # 依赖快照字段声明（install_deps 动态展开，mypy 显式化；对象身份与 Dependencies 共享）
    _engine: str
    _config: AppConfig
    _llm: LLMClient | None
    _use_llm: bool
    _event_sink: Callable[[ProgressEvent], None] | None
    _stream_sink: Callable[[Any], None] | None
    _memory: IFourLayerMemory | None
    _tool_dispatcher: object | None
    _max_parallel_tool_calls: int
    _extractor: WebExtractor
    _domain_pack: DomainPack
    _builder: ReportBuilder
    _budget: BudgetController
    _timeline: TimelineMemory
    _approval_enabled: bool
    _approval_policy: ApprovalPolicy
    _store: CompetitorStore | None
    _ingester: Ingester | None
    _retriever: Retriever | None
    _vector_store: VectorStore | None
    _reranker: CrossEncoderReranker | None
    _discoverer: CompetitorDiscoverer
    _tracer: Any

    _deps: Dependencies
    _host: Any

    def __init__(self, deps: Dependencies, host: Any) -> None:
        self._deps = deps
        self._host = host
        install_deps(deps, self)

    def _emit(self, event: ProgressEvent) -> None:
        if self._event_sink is not None:
            self._event_sink(event)

    def _default_llm(self) -> LLMClient:
        """懒构造默认 LLM 客户端——实现在门面（缓存单点），服务经 host 委派。"""
        return self._host._default_llm()

    def _memory_ctx_for(self, competitor: str, task: str) -> str:
        """记忆召回——实现在门面（测试实例级 patch 接缝），服务经 host 委派。"""
        return self._host._memory_ctx_for(competitor, task)


def build_default_llm(config: AppConfig, tracer: Any) -> LLMClient:
    """默认 LLM 客户端构造（设计文档 74 §3.1，doc 78 迁移至装配层）。

    端点/模型从 ``config.llm`` 显式注入：默认构造不静默继承 shell env 的
    ``OPENAI_BASE_URL``/API Key，以 ``review_config.yaml`` 的 ``llm`` 段为准——
    根治 shell env 污染导致的误用端点（0ms 空返回、401）。
    同时检测 env 与 config 的端点漂移并告警（§3.1 思路 1，配置漂移检测）。
    懒缓存单点在门面（``CompetitorAnalysisAPI._default_llm_client``）。
    """
    cfg_llm = config.llm
    env_base = os.getenv("OPENAI_BASE_URL")
    if cfg_llm.api_base_url and env_base and env_base.rstrip("/") != cfg_llm.api_base_url.rstrip("/"):
        logger.warning(
            "LLM 端点漂移检测（设计文档 74 §3.1）: env OPENAI_BASE_URL=%s 与 "
            "config.llm.api_base_url=%s 不一致，采用 config 声明端点；如需自定义端点请改 "
            "review_config.yaml 的 llm 段（api_base_url/model）",
            env_base,
            cfg_llm.api_base_url,
        )
    client = LLMClient(
        model=cfg_llm.model or "deepseek-chat",
        base_url=cfg_llm.api_base_url or None,
        fallback_models=cfg_llm.fallback_models,
        timeout=cfg_llm.timeout,
        max_retries=cfg_llm.max_retries,
        pricing_per_1k=cfg_llm.pricing_per_1k,
        tracer=tracer,
    )
    logger.info(
        "LLM 端点（设计文档 74 §3.1）: model=%s base_url=%s",
        client._model,
        cfg_llm.api_base_url or "（未指定，用 SDK 默认）",
    )
    return client
