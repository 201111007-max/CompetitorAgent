"""CompetitorAnalysisAPI — 外部唯一入口（门面薄路由，设计文档 78 §2）。

宿主：``assembly`` 依赖装配 → ``Dependencies``；``analysis_service`` 单竞品分析 +
Lead 编排（``_react_loop`` 闭包组整体）+ 记忆/RAG/复核簇；``compare_service``
compare/discover + comparison 组装；``schedule_service`` 调度/周报/续跑/历史。
冻结契约（doc 78 §4.2 快照单测守护）：公共方法签名逐位不变、四入口零改动；
私有属性经 ``install_deps`` 同名展开（与依赖快照共享对象身份）；``_default_llm``/
``_memory_ctx_for`` 留门面作 patch 接缝；跨服务调用经 host 由门面统一编排。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

# 导入顺序契约：analysis_service 先触发 agent→mcp 初始化环闭合（doc 78 由门面统一保证）
from competitor_agent.facade.analysis_service import (
    AnalysisService,
    _subagent_event_sink,  # noqa: F401 — 兼容旧导入路径（doc 63 §13 子 Agent 事件过滤器）
)
from competitor_agent.facade.assembly import build_default_llm, build_dependencies, install_deps
from competitor_agent.facade.compare_service import CompareService
from competitor_agent.facade.schedule_service import ScheduleService

if TYPE_CHECKING:
    from competitor_agent.collector.web_extractor import WebExtractor
    from competitor_agent.config.loader import AppConfig
    from competitor_agent.core.alerting import Alert, AlertSink
    from competitor_agent.domain_types.events import ProgressEvent
    from competitor_agent.domain_types.report import (
        ChatResult,
        ComparisonReport,
        CompetitorReport,
    )
    from competitor_agent.interfaces.context import ChatMessage
    from competitor_agent.interfaces.memory import IFourLayerMemory
    from competitor_agent.knowledge_base.competitor_store import CompetitorStore
    from competitor_agent.knowledge_base.reranker import CrossEncoderReranker
    from competitor_agent.knowledge_base.vector_store import VectorStore
    from competitor_agent.llm.client import LLMClient
    from competitor_agent.memory.timeline_memory import TimelineMemory

logger = logging.getLogger("competitor_agent.facade.api")


class CompetitorAnalysisAPI:
    """竞品分析外部入口"""

    _config: AppConfig
    _tracer: Any
    _event_sink: Callable[[ProgressEvent], None] | None
    _memory: IFourLayerMemory | None
    _timeline: TimelineMemory

    def __init__(
        self,
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
    ) -> None:
        # 装配（build_dependencies 与本签名同名同参）+ 依赖快照按原私有名展开
        deps = build_dependencies(**{k: v for k, v in locals().items() if k != "self"})
        install_deps(deps, self)
        self._default_llm_client: LLMClient | None = None
        # 三服务构造（doc 78 §2.1）：host 反引用支撑跨服务编排与测试 patch 接缝
        self._analysis = AnalysisService(deps, host=self)
        self._compare = CompareService(deps, host=self)
        self._schedule = ScheduleService(deps, host=self)

    def _default_llm(self) -> LLMClient:
        """默认 LLM 客户端（设计文档 74 §3.1）：懒缓存单点，构造在装配层 build_default_llm。"""
        if self._default_llm_client is None:
            self._default_llm_client = build_default_llm(self._config, self._tracer)
        return self._default_llm_client

    def _memory_ctx_for(self, competitor: str, task: str) -> str:
        """按已知竞品名做记忆召回（子 Agent 复用，避免逐子 Agent 重复解析任务）。"""
        if self._memory is None or not competitor or competitor == "unknown":
            return ""
        try:
            return "\n".join(self._memory.recent_context(competitor, top_k=3, query=task))
        except Exception:
            logger.warning("ReAct 记忆召回失败: %s", competitor, exc_info=True)
            return ""

    # ── 分析入口（宿主：analysis_service）─────────────────────────────

    def analyze(
        self,
        task: str,
        conversation_history: list[ChatMessage] | None = None,
        mode: str = "team",
        session_id: str | None = None,
    ) -> CompetitorReport | ChatResult:
        return self._analysis.analyze(task, conversation_history=conversation_history, mode=mode, session_id=session_id)

    def analyze_react(self, task: str, session_id: str | None = None) -> str:
        return self._analysis.analyze_react(task, session_id=session_id)

    def analyze_react_report(self, task: str, session_id: str | None = None) -> CompetitorReport:
        return self._analysis.analyze_react_report(task, session_id=session_id)

    def analyze_team(
        self,
        task: str,
        session_id: str | None = None,
        max_retries: int = 1,
    ) -> CompetitorReport | ChatResult:
        return self._analysis.analyze_team(task, session_id=session_id, max_retries=max_retries)

    async def analyze_team_async(
        self,
        task: str,
        session_id: str | None = None,
        max_retries: int = 1,
        max_parallel: int = 4,
    ) -> CompetitorReport | ChatResult:
        return await self._analysis.analyze_team_async(
            task, session_id=session_id, max_retries=max_retries, max_parallel=max_parallel
        )

    async def analyze_stream(self, task: str, session_id: str | None = None) -> AsyncIterator[ProgressEvent]:
        async for event in self._analysis.analyze_stream(task, session_id=session_id):
            yield event

    def run(
        self,
        task: str,
        *,
        session_id: str | None = None,
        history_messages: list[dict[str, str]] | None = None,  # 设计文档 65 §3.3：多轮会话历史
    ) -> CompetitorReport | ComparisonReport | ChatResult:
        return self._analysis.run(task, session_id=session_id, history_messages=history_messages)

    def verify_report(self, competitor: str, mode: str | None = None) -> Any:
        """报告级 NLI 事实校验（设计文档 77 §2.3 产品侧挂点，门面薄路由）。"""
        return self._analysis.verify_report(competitor, mode=mode)

    # ── 对比/发现（宿主：compare_service）─────────────────────────────

    def discover(self, task: str) -> ComparisonReport:
        return self._compare.discover(task)

    def compare(self, *competitors: str) -> ComparisonReport:
        return self._compare.compare(*competitors)

    # ── 调度/周报/历史/续跑（宿主：schedule_service）──────────────────

    def report_diff(self, prev: CompetitorReport, cur: CompetitorReport) -> list[Alert]:
        return self._schedule.report_diff(prev, cur)

    def run_scheduled(
        self,
        competitors: list[str] | None = None,
        alert_sink: AlertSink | None = None,
    ) -> list[CompetitorReport]:
        return self._schedule.run_scheduled(competitors, alert_sink=alert_sink)

    def build_weekly_report(self) -> tuple[Path, Path]:
        return self._schedule.build_weekly_report()

    def cancel(self, session_id: str) -> None:
        self._schedule.cancel(session_id)

    def resume(self, session_id: str) -> CompetitorReport:
        return self._schedule.resume(session_id)

    def continue_analysis(self, session_id: str) -> CompetitorReport:
        return self._schedule.continue_analysis(session_id)

    def get_history(self, competitor: str | None = None) -> list[CompetitorReport]:
        return self._schedule.get_history(competitor)

    def build_dossier(self, competitor: str, window_days: int | None = None) -> Any:
        return self._schedule.build_dossier(competitor, window_days=window_days)

    def refresh_stale(
        self,
        ttl_override: dict[str, int] | None = None,
        recompute_all: bool = False,
    ) -> list[CompetitorReport]:
        return self._schedule.refresh_stale(ttl_override, recompute_all=recompute_all)

    # ── 属性（签名冻结）───────────────────────────────────────────────

    @property
    def memory(self) -> IFourLayerMemory | None:
        return self._memory

    @property
    def timeline(self) -> TimelineMemory:
        return self._timeline

    # ── 私有路由：测试直接调用/实例级 patch 的兼容接缝（doc 78 §2.2 规则 5）──
    # 服务侧对应调用点经 self._host 委派回门面，实例级 patch 语义保持不变。

    def _react_loop(
        self,
        task: str,
        session_id: str | None,
        *,
        system_prompt: str | None = None,
        plan_first: bool = True,
        final_as_payload: bool = True,
        history_messages: list[dict[str, str]] | None = None,
    ) -> Any:
        return self._analysis._react_loop(
            task,
            session_id,
            system_prompt=system_prompt,
            plan_first=plan_first,
            final_as_payload=final_as_payload,
            history_messages=history_messages,
        )

    def _run_react_loop(
        self,
        task: str,
        session_id: str | None,
        history_messages: list[dict[str, str]] | None = None,
    ) -> Any:
        return self._analysis._run_react_loop(task, session_id, history_messages=history_messages)

    def _react_competitor(self, task: str) -> Any:
        return self._analysis._react_competitor(task)

    def _react_memory_context(self, task: str) -> str:
        return self._analysis._react_memory_context(task)

    def _react_rag_context(self, task: str) -> str:
        return self._analysis._react_rag_context(task)

    def _react_web_extract(self, url: str) -> str:
        return self._analysis._react_web_extract(url)

    def _web_extract_checked(self, url: str, fetch_policy: Any = None) -> str:
        return self._analysis._web_extract_checked(url, fetch_policy)

    def _lead_web_extract(
        self, competitor_fn: Callable[[], str], fetch_policy: Any = None
    ) -> Callable[[str], str]:
        return self._analysis._lead_web_extract(competitor_fn, fetch_policy)

    def _ingest_fetched(self, competitor: str, dimension: str, url: str, text: str) -> None:
        self._analysis._ingest_fetched(competitor, dimension, url, text)

    def _build_kb_recall(self, competitor_fn: Callable[[], str], dimension: str = "") -> Any:
        return self._analysis._build_kb_recall(competitor_fn, dimension)

    def _export_comparison_json(self, report: ComparisonReport) -> Path | None:
        return self._compare._export_comparison_json(report)

    def _finalize_comparison_report(
        self, loop: Any, result: Any, plan: dict[str, Any], sid: str, terminal: str
    ) -> ComparisonReport:
        return self._compare._finalize_comparison_report(loop, result, plan, sid, terminal)

    def _record_timeline(self, report: CompetitorReport) -> list[Any]:
        return self._analysis._record_timeline(report)

    def _build_alert_sink(self) -> AlertSink:
        return self._schedule._build_alert_sink()

    def _apply_verification_to_approval(self, competitor: str, verification: Any) -> None:
        self._analysis._apply_verification_to_approval(competitor, verification)

    def _latest_report_text(self, competitor: str) -> str:
        return self._analysis._latest_report_text(competitor)

    def _task_with_sources(self, competitor: Any) -> str:
        return self._compare._task_with_sources(competitor)

    def _tracked_competitors(self) -> list[str]:
        return self._schedule._tracked_competitors()

    @staticmethod
    def _plan_resolution(
        plan: dict[str, Any] | None,
        parsed: Any,
        candidate_count: int = 0,
    ) -> str:
        return AnalysisService._plan_resolution(plan, parsed, candidate_count)
