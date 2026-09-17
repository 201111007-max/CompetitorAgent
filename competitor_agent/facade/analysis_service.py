"""单竞品分析服务（设计文档 78 §2.1）：Lead 编排 + run/analyze/chat/langgraph 路径。

doc 78 §2.2 规则 1：``_react_loop`` 闭包组（plan_box/pinned_facts/delegate_collector/
_lead_competitor_now/_collect_pinned）整体迁入本模块，不拆散。跨服务调用经
``self._host``（门面）路由：``_run_react_loop``/``_react_competitor``/``_react_web_extract``/
``_ingest_fetched`` 经由门面委派以保留测试实例级 patch 接缝与懒构造单点；
记忆召回（``_memory_ctx_for``）与默认 LLM（``_default_llm``）由 ServiceBase 委派门面。
日志命名空间保持 ``competitor_agent.facade.api``（caplog 断言兼容）。
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Callable

from competitor_agent.agent.aggregate_tool import make_aggregate_tool
from competitor_agent.agent.delegate_tool import (
    DelegateRunner,
    SubagentRuntime,
    make_delegate_tool,
)
from competitor_agent.agent.make_plan import build_make_plan_tool
from competitor_agent.agent.prompts.react_system import (
    build_chat_system_prompt,
    build_lead_system_prompt,
)
from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.agent.react_loop import ReactLoop, ReactRunResult
from competitor_agent.agent.review_tools import (
    build_check_freshness_tool,
    build_detect_conflict_tool,
    build_select_source_tool,
    build_validate_facts_tool,
    extract_verified_facts,
)
from competitor_agent.agent.stagnation import StagnationConfig
from competitor_agent.agent.subagent_registry import (
    build_subagent,
    get_subagent_registry,
)
from competitor_agent.agent.tool_dispatcher import ToolSpec
from competitor_agent.agent.tool_registry import build_react_dispatcher
from competitor_agent.core.approval_gate import decide_approval
from competitor_agent.core.checkpoint import (
    delete_checkpoint,
    is_cancelled,
    save_checkpoint,
)
from competitor_agent.core.input_sanitizer import sanitize_task
from competitor_agent.core.report_exporter import export_competitor_json
from competitor_agent.core.reuse_dimensions import reuse_dimension_results
from competitor_agent.core.url_guard import URLError, guard_http_url
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import GapStatus
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.domain_types.freshness import ReportFreshness
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.pricing import profile_from_details
from competitor_agent.domain_types.report import (
    CancelledResult,
    ChatResult,
    ComparisonReport,
    CompetitorReport,
)
from competitor_agent.facade import react_report
from competitor_agent.facade.assembly import Dependencies, ServiceBase
from competitor_agent.interfaces.context import (
    AnalysisSession,
    ChatMessage,
    Skill,
    SourceContext,
)
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError
from competitor_agent.observability.logger import (
    close_session_log,
    get_session_logger,
    log_event,
    set_current_session,
)

logger = logging.getLogger("competitor_agent.facade.api")

# 设计文档 63 §13 主旨2：子 Agent 思考/进度事件不入 Lead 气泡（Web 层会把这几类收敛为
# text_delta，若子 Agent 透传会污染 Lead 流）。error/cancelled 等诊断事件仍透传。
_SUBAGENT_HIDDEN_EVENTS = frozenset({"phase_start", "phase_complete", "progress"})


def _subagent_event_sink(
    event_sink: Callable[[Any], None] | None,
) -> Callable[[Any], None] | None:
    """为子 Agent 构造事件过滤器（设计文档 63 §13 主旨2）：思考/进度事件丢弃不入 Lead 流。

    子 Agent 后台执行，其 phase_start/phase_complete/progress 属"思考过程"，按主旨2 不展示；
    非叙述型事件（error/cancelled 等诊断）仍透传。``event_sink`` 为 None 时返回 None。
    """
    if event_sink is None:
        return None

    def _sink(event: Any) -> None:
        if getattr(event, "event", None) in _SUBAGENT_HIDDEN_EVENTS:
            return
        event_sink(event)

    return _sink


def _delegate_section_url(result: str, dimension: str) -> str:
    """delegate 批量回填文本中该维度子结果块的首个 URL（按结果头切分）。"""
    import re as _re

    marker = f"[维度子 Agent 结果: {dimension}"
    idx = result.find(marker)
    if idx < 0:
        marker = f"（请分析维度：{dimension}）"
        idx = result.find(marker)
    if idx < 0:
        return ""
    match = _re.search(r"https?://[^\s\"'<>\]\)]+", result[idx:])
    return match.group(0) if match else ""


class AnalysisService(ServiceBase):
    """单竞品分析 + Lead 编排（doc 78 §2.1；依赖经 ServiceBase 按原私有名展开）。"""

    def __init__(self, deps: Dependencies, host: Any) -> None:
        super().__init__(deps, host)

    def analyze(
        self,
        task: str,
        conversation_history: list[ChatMessage] | None = None,
        mode: str = "team",
        session_id: str | None = None,
    ) -> CompetitorReport:
        """单竞品分析（设计文档 49）：Lead ReAct 编排 → CompetitorReport。

        Args:
            task: 用户任务文本（入站先做浅清洗 sanitize_task）
            conversation_history: 上一轮对话历史（ChatMessage 列表），
                传入则按注册表子串匹配消歧（承接上文竞品），支持多轮追问。
            mode: 已废弃（历史兼容，仅告警）；统一走 Lead ReAct 编排。
            session_id: 外部会话 ID（如 Web 端 sid）。传入时复用，使内部取消标志
                与外部一致（解决 Web 取消断链）；留空则自动生成。

        设计文档 96：意图门控随 parse_task 退役而删除——本方法恒产报告
        （对话语义请走 ``run_conversation()``）。
        """
        if mode != "team":
            logger.warning("mode 参数已废弃（历史兼容），统一走 Lead ReAct 编排，忽略 mode=%s", mode)
        task = sanitize_task(task)
        task = self._disambiguate_with_history(task, conversation_history)
        sid = session_id or f"sess_{uuid.uuid4().hex[:8]}"
        set_current_session(sid)
        # 设计文档 54：trace 生命周期——trace_id 即 session_id，覆盖本次分析
        # （含并行子 Agent 的跨线程 span，经 Tracer._traces 聚合 cost/token）。
        self._tracer.start_trace("analyze", trace_id=sid, input_brief=task)
        try:
            slog = get_session_logger(sid)
            log_event(slog, "session_started", "init", f"会话 {sid} 启动", task=task)
            self._emit(
                ProgressEvent(
                    event="phase_start",
                    phase="langgraph" if self._engine == "langgraph" else "react",
                    message=f"{'LangGraph' if self._engine == 'langgraph' else 'Lead'} 编排: {task}",
                )
            )

            if self._engine == "langgraph":
                # 设计文档 51：LangGraph 引擎——取消/预算/checkpoint 不对齐（差异化结论）
                plan, answer, transcript = self._run_langgraph_engine(task, sid)
                terminal = "success"
                error_kind = ""
            else:
                loop, result = self._host._run_react_loop(task, sid)
                plan, answer, transcript = loop.plan, result.answer, result.transcript
                terminal = (
                    "cancelled"
                    if result.cancelled
                    else ("partial" if result.budget_exhausted else "success")
                )
                error_kind = result.error_kind
            report = react_report.assemble(
                lead_answer=answer,
                competitor=self._lead_competitor(task, plan),
                loop_plan=plan,
                transcript=transcript,
                builder=self._builder,
                terminal_state=terminal,
                error_kind=error_kind,
            )
            # 设计文档 62 §3.5：组装后收尾提取为共享 helper（analyze/run registry 分型共用）
            return self._finalize_competitor_report(report, task, sid, transcript, terminal)
        except Exception:
            # 异常路径：闭合 trace 为 error，避免残留悬半根节点（设计文档 54 §2.2）
            logger.warning("analyze 会话 %s 异常终止", sid, exc_info=True)
            self._tracer.end_trace(sid, status="error", output_brief="")
            raise

    def _finalize_competitor_report(
        self,
        report: CompetitorReport,
        task: str,
        sid: str,
        transcript: list[dict],
        terminal: str,
        *,
        own_context: bool = True,
    ) -> CompetitorReport:
        """单竞品报告组装后收尾（log/记忆/取消 checkpoint/时间线/归档/导出/事件/trace）。

        由 analyze()（registry 单竞品）与 run()（registry 分型）共用；返回最终报告
        （正常 CompetitorReport 或取消时的 CancelledResult）。异常路径的 trace 闭合
        由调用方 try/except 负责。

        ``own_context``（设计文档 96）：False = generate_report 子流程——close log 与
        end_trace 归对话环拥有，此处跳过（其余收尾照常）。
        """
        # 设计文档 88 §4.4：writer 叙事槽（report.writer_pass 开关，默认关）。挂在 finalize
        # 顶部 = analyze 双引擎（react/langgraph）与 run 两路径的单点汇聚；仅正常终态写作
        # （取消/预算耗尽无完整事实源）。时间线段落追加在其后，「## 竞品时间线」串不受影响。
        if self._config.report.writer_pass and terminal == "success":
            from competitor_agent.facade import writer_pass as _writer_pass

            _writer_pass.maybe_run_writer_pass(
                report,
                llm=self._llm,
                stream_sink=self._stream_sink,
                config=self._config.report,
                on_skeleton=self._emit_report_skeleton,
            )
        slog = get_session_logger(sid)
        log_event(
            slog, "report.built", "report",
            f"报告生成，{len(report.dimension_results)} 个维度",
            dimension_count=len(report.dimension_results),
            overall_confidence=round(report.overall_confidence, 3),
        )
        # 记忆沉淀（唯一写侧）：成功与取消部分结果都沉淀（对齐 single 路径）
        self._record_memory_success(report, transcript)
        if is_cancelled(sid):
            # 取消完成：保留 checkpoint 供 /resume 续跑，返回带部分结果的取消报告
            logger.info("会话 %s 取消后返回部分结果（%d 个维度）", sid, len(report.dimension_results))
            self._save_checkpoint_for_resume(sid, task, report)
            if own_context:
                close_session_log(sid)
            self._emit(
                ProgressEvent(
                    event="cancelled",
                    phase="report",
                    message=f"分析已取消，返回 {len(report.dimension_results)} 个已完成维度",
                )
            )
            if own_context:
                self._tracer.end_trace(
                    sid, status="cancelled", output_brief=report.markdown_report
                )
            return CancelledResult(
                competitor=report.competitor,
                dimension_results=report.dimension_results,
                overall_score=report.overall_score,
                overall_confidence=report.overall_confidence,
                gaps_pending=report.gaps_pending,
                markdown_report=report.markdown_report,
                terminal_state="cancelled",
                created_at=report.created_at,
                cancelled=True,
            )
        # 分析正常完成：记录时间线 diff + 归档带新鲜度的会话（设计文档 26）
        # 设计文档 67 §3.2：diff 事件 + 新增竞品判定喂审批门 → 报告 JSON status 字段
        is_new_competitor = self._timeline.report_for(report.competitor.name) is None
        timeline_events = self._record_timeline(report)
        self._archive_report(report, task, sid)
        self._export_competitor_json(
            report,
            sid,
            timeline_events=timeline_events,
            is_new_competitor=is_new_competitor,
        )
        delete_checkpoint(sid)
        if own_context:
            close_session_log(sid)
        self._emit(
            ProgressEvent(
                event="report",
                phase="report",
                progress=1.0,
                message=f"报告生成完成，终态={terminal}",
            )
        )
        if own_context:
            self._tracer.end_trace(sid, status=terminal, output_brief=report.markdown_report)
        return report

    @staticmethod
    def _plan_resolution(
        plan: dict[str, Any] | None,
        candidate_count: int = 0,
    ) -> str:
        """组装分型（设计文档 96：parse_task 判型回退退役）：plan.resolution 优先。

        registry（单竞品）→ CompetitorReport；compare/discovery → ComparisonReport。

        plan 缺 resolution 时：plan.competitors → compare（用户点名多竞品）；
        candidate_count > 0 → discovery（Lead 实际做了候选枚举/委派，设计文档 65 §2.3
        回归——避免多候选任务误判 registry 走单报告路径）；否则 registry。
        设计文档 66 §3.2 的 parse_task（LLM）意图回退随 parse_task 退役而移除
        （generate_report 结构化参数并入子任务文本，由子 loop make_plan 补偿）。
        """
        resolution = str((plan or {}).get("resolution") or "").lower()
        if resolution:
            return resolution
        if (plan or {}).get("competitors"):
            return "compare"
        if candidate_count > 0:
            return "discovery"
        return "registry"

    def _web_search_candidates(self, scope: str) -> str:
        """候选竞品枚举工具（设计文档 62 §3.2）：联网返回候选清单 JSON，供 Lead DISCOVERY 编排。

        Observation 为候选列表（name + official_links），Lead 读取后 delegate(targets=候选)。
        逐候选实时推送 ``discovery.candidate`` + 汇总 ``discovery`` 事件（Web SSE 契约，
        沿用 _run_discovery 时代的相位；枚举失败/无候选 → 可读回灌供 Lead 自恢复）。
        """
        import json as _json

        try:
            raw = self._discoverer.candidates(scope or "")
        except Exception:  # 枚举失败可回灌自恢复
            logger.warning("候选竞品枚举失败: scope=%r", scope, exc_info=True)
            return "候选竞品枚举失败（联网搜索不可用），请改用已注册竞品或缩小 scope。"
        names = [str(c.get("name")) for c in raw if c.get("name")]
        if not raw:
            return f"未发现候选竞品（scope={scope!r}）。"
        for name in names:
            self._emit(
                ProgressEvent(
                    event="discovery.candidate",
                    phase="strategic",
                    message=f"发现候选: {name}",
                    payload={"candidate": name},
                )
            )
        self._emit(
            ProgressEvent(
                event="discovery",
                phase="strategic",
                message=f"发现 {len(names)} 个候选竞品: {', '.join(names)}",
                payload={"candidates": names},
            )
        )
        return _json.dumps(raw, ensure_ascii=False)

    def _record_timeline(self, report: CompetitorReport) -> list[Any]:
        """记录竞品时间线 diff（设计文档 26 §3.4），并把事件段落追加进 Markdown。

        返回本次 diff 事件列表（设计文档 67 §3.2 审批门消费）；失败仅告警返回空。
        """
        try:
            events = self._timeline.update(report)
        except Exception:  # 时间线记录失败不影响主流程，仅告警
            logger.warning("时间线记录失败: %s", report.competitor.name, exc_info=True)
            return []
        if events:
            section = self._builder.render_timeline(events)
            if section:
                report.markdown_report = report.markdown_report.rstrip() + "\n\n" + section + "\n"
        return events

    def _archive_report(self, report: CompetitorReport, task: str, session_id: str) -> None:
        """归档会话（统一 raw schema + freshness 元数据 + 定价画像），
        供 refresh_stale 判定过期、定价成本对比与时间线 diff。"""
        if self._memory is None:
            return
        pricing_profiles = [
            profile.to_dict()
            for r in report.dimension_results
            if r.dimension == "pricing"
            and isinstance(r.details, dict)
            and (profile := profile_from_details(r.details, r.evidence or [])).has_pricing_data
        ]
        self._memory.archive_session(
            AnalysisSession(
                task=task,
                competitor_name=report.competitor.name,
                session_id=session_id,
                raw={
                    "markdown_report": report.markdown_report,
                    "terminal_state": report.terminal_state,
                    "dimension_count": len(report.dimension_results),
                    "competitor_name": report.competitor.name,
                    "created_at": report.created_at,
                    "freshness": report.freshness.to_dict() if report.freshness else None,
                    "pricing_profiles": pricing_profiles,
                    # 设计文档 35：结构化维度 + 遗留缺口，供会话摘要/相关度召回
                    "dimensions": [
                        {"dimension": r.dimension, "summary": r.summary, "confidence": r.confidence}
                        for r in report.dimension_results
                    ],
                    "pending_gaps": [g.field for g in report.gaps_pending],
                },
            )
        )

    def _export_competitor_json(
        self,
        report: CompetitorReport,
        session_id: str,
        *,
        timeline_events: list[object] | None = None,
        is_new_competitor: bool = False,
    ) -> Path | None:
        """设计文档 28：config.report.export_json 开启时导出 <data_dir>/reports/competitor/<竞品>.json。

        结构化副本与 .md 同目录同名；成功后在报告正文末尾追加"已导出 JSON 路径"提示。
        设计文档 67 §3.1/§3.2：审批门决定 JSON ``status``（触发规则 → pending_review）；
        ``report.export_html`` 开启时追加导出单文件自包含 HTML。
        失败仅告警不影响主流程；成功返回落盘路径。
        """
        if not self._config.report.export_json:
            return None
        try:
            approval_status = (
                decide_approval(
                    report,
                    timeline_events=timeline_events,
                    is_new_competitor=is_new_competitor,
                    policy=self._approval_policy,
                )
                if self._approval_enabled
                else "approved"
            )
            path = export_competitor_json(report, self._config.report.output_dir, approval_status=approval_status)
        except Exception:
            logger.warning("JSON 导出失败（竞品: %s）: ", report.competitor.name, exc_info=True)
            return None
        try:
            note = f"\n> 结构化数据已导出: `{path}`\n"
            if report.markdown_report and note.strip() not in report.markdown_report:
                report.markdown_report = report.markdown_report.rstrip() + "\n" + note
        except Exception:
            logger.warning("竞品 JSON 导出提示追加失败: %s", report.competitor.name, exc_info=True)
        if self._config.report.export_html:
            self._export_competitor_html(report)
        return path

    def _export_competitor_html(self, report: CompetitorReport) -> Path | None:
        """设计文档 67 §3.1：报告落盘后导出单文件自包含 HTML（report.export_html 开启）。"""
        try:
            from competitor_agent.core.report_visuals import render_html

            path = render_html(report)
        except Exception:
            logger.warning("HTML 导出失败（竞品: %s）: ", report.competitor.name, exc_info=True)
            return None
        try:
            note = f"\n> 可分享 HTML 已导出: `{path}`\n"
            if report.markdown_report and note.strip() not in report.markdown_report:
                report.markdown_report = report.markdown_report.rstrip() + "\n" + note
        except Exception:
            logger.warning("竞品 HTML 导出提示追加失败: %s", report.competitor.name, exc_info=True)
        return path

    def analyze_react(self, task: str, session_id: str | None = None) -> str:
        """ReAct 交互入口（设计文档 40/49）：Lead 编排循环，返回结论文本。

        与 analyze() 同源（make_plan 首步 + delegate + 复核工具），仅返回裸文本。
        """
        _, result = self._host._run_react_loop(task, session_id)
        return result.answer

    def analyze_react_report(self, task: str, session_id: str | None = None) -> CompetitorReport:
        """ReAct 结构化入口（设计文档 43 §2.3 兼容）：产物入 CompetitorReport。

        复用与 analyze() 同源的 Lead 编排；结论文本按 REPORT_SCHEMA JSON
        组装为多维度报告，非 JSON 降级为单 react 维度（react_report.assemble）。
        """
        loop, result = self._host._run_react_loop(task, session_id)
        terminal = (
            "cancelled"
            if result.cancelled
            else ("partial" if result.budget_exhausted else "success")
        )
        return react_report.assemble(
            lead_answer=result.answer,
            competitor=self._lead_competitor(task, loop.plan),
            loop_plan=loop.plan,
            transcript=result.transcript,
            builder=self._builder,
            terminal_state=terminal,
            error_kind=result.error_kind,
        )

    def _run_react_loop(
        self,
        task: str,
        session_id: str | None,
        history_messages: list[dict[str, str]] | None = None,  # 设计文档 65 §3.3
    ) -> tuple[ReactLoop, ReactRunResult]:
        """构建 Lead ReactLoop 并运行；会话收尾统一回收子 Agent 线程池。

        DelegateRunner 挂在 loop 实例（而非 self），避免并行 analyze()（compare
        并发）共享 self._delegate_runner 时互相 shutdown 彼此的线程池。
        """
        loop = self._react_loop(task, session_id, history_messages=history_messages)
        try:
            result = loop.run_with_result(task)
        finally:
            runner = getattr(loop, "_delegate_runner", None)
            if runner is not None:
                runner.shutdown()
        if result.steps:
            self._budget.record_iteration()
        return loop, result

    def _run_langgraph_engine(
        self, task: str, session_id: str | None
    ) -> tuple[dict | None, str, list[dict]]:
        """LangGraph 引擎路径（设计文档 51 §2.2）：StateGraph 编排，其余全复用。

        与 ``_run_react_loop`` 同形返回 ``(plan, answer, transcript)``：
        LLM/工具/记忆/RAG/事件/报告出口与自研引擎逐位一致（对照实验控变量），
        唯一变量是编排层（StateGraph plan→Send fan-out→aggregate→report）。
        取消/预算/checkpoint 不做图级对齐（§1.2 差异化结论）；
        预算记账以 transcript 记录数近似步数（同 0.01/步 口径）。
        """
        from competitor_agent.agent.langgraph_engine import run_langgraph

        llm = self._llm or self._default_llm()
        lead_competitor = self._host._react_competitor(task)

        def _subagent_run(name: str, sub_task: str) -> ReactRunResult:
            # �?Agent 运行时与自研路径同工厂（共享取消/记忆/RAG/事件）；
            # 迭代限制已移除（max_steps=None 无限循环，靠 LLM 自然收敛 Final Answer）。
            # 设计文档 71 §5.3：LangGraph 子 Agent 与 Lead 共享同一 per-run 抓取护栏
            return build_subagent(
                name,
                llm,
                config=self._config,
                web_extract=self._web_extract_for(lead_competitor.name, name, lg_fetch_policy),
                session_id=session_id,
                memory_context_fn=lambda t: self._memory_ctx_for(lead_competitor.name, t),
                rag_fn=lambda t: self._rag_ctx_for(lead_competitor.name, t),
                event_sink=self._event_sink,
                obs_max_chars=self._config.collector.max_content_chars,
                max_steps=None,
                tracer=self._tracer,  # 设计文档 54：子 Agent span
                max_parallel_tool_calls=self._max_parallel_tool_calls,
            ).run_subagent(sub_task)

        # Lead 系统提示与自研路径同（设计文档 60：单协议，无工具描述/格式说明）
        # 设计文档 71 §5.3：LangGraph 路径同样装配 per-run 抓取护栏
        from competitor_agent.collector.fetch_policy import FetchPolicy

        lg_fetch_policy = FetchPolicy(max_per_run=self._config.collector.fetch_max_per_run)
        prompt_dispatcher = build_react_dispatcher(
            config=self._config,
            web_extract=lambda url: self._web_extract_checked(url, lg_fetch_policy),
            exclude=("analyze_competitor",),
            extra_tools={"make_plan": build_make_plan_tool(allowed_dimensions=self._domain_pack.dimension_names)},
            tracer=self._tracer,
        )
        base_prompt = ReactAgent(
            llm=llm, dispatcher=prompt_dispatcher
        ).build_system_prompt(
            instructions=build_lead_system_prompt()
        )
        plan, answer, transcript = run_langgraph(
            task,
            llm=llm,
            make_plan_fn=build_make_plan_tool(allowed_dimensions=self._domain_pack.dimension_names),
            subagent_run=_subagent_run,
            registry=get_subagent_registry(),
            event_sink=self._event_sink,
            session_id=session_id,
            memory_ctx_fn=self._host._react_memory_context,
            rag_fn=self._host._react_rag_context,
            system_prompt=base_prompt,
        )
        if transcript:
            self._budget.record_iteration()
        return plan, answer, transcript

    def _react_loop(
        self,
        task: str,
        session_id: str | None,
        *,
        system_prompt: str | None = None,
        plan_first: bool = True,
        final_as_payload: bool = True,
        history_messages: list[dict[str, str]] | None = None,  # 设计文档 65 §3.3：多轮会话历史
    ) -> ReactLoop:
        """组装 Lead ReactLoop（设计文档 49 §3.5/3.6）：plan-first + delegate + 复核工具。

        - ``exclude=("analyze_competitor",)``：防递归调用 analyze()；
        - ``extra_tools``：make_plan（首步强制）+ delegate（后台并发委派）+ 复核工具；
        - 子 Agent 运行时经 ``DelegateRunner`` 后台线程池执行，共享取消/记忆/RAG；
        - ``system_prompt``/``plan_first``/``final_as_payload``：设计文档 64 §5.2 对话式
          分支复用——普通提问传 ``build_chat_system_prompt()`` + ``plan_first=False`` +
          ``final_as_payload=False``（不强制 make_plan、最终文本走 Stream 通道）。
        """
        if not self._config.subagents.enabled:
            from competitor_agent.interfaces.exceptions import CompetitorAgentError

            raise CompetitorAgentError("subagents.enabled=false 时 analyze() 主路径不可用（设计文档 49）")
        # 设计文档 62 §3.8：delegate 并发硬上限 = execution.max_parallel_subagents（不再自决）
        max_concurrent = self._config.execution.max_parallel_subagents
        max_candidates = self._config.execution.max_discover_candidates
        timeout_seconds = self._config.subagents.timeout_seconds
        lead_competitor = self._host._react_competitor(task)
        # 设计文档 62 §3.5：候选子 Agent 结构化结果收集器（comparison 组装器读取）
        delegate_collector: dict[str, dict[str, Any]] = {}
        # 设计文档 62 §3.6/§3.9：子 Agent 沿用 react_agent 默认压缩保留步数；
        # Lead 编排会话用独立 lead.max_history_steps（候选委派回填更长）
        agent_max_history_steps = self._config.agent.max_history_steps
        lead_max_history_steps = self._config.lead.max_history_steps
        # 设计文档 71 §5.3/§6.1：per-run 抓取策略（单跑上限 + 同 URL 去重），跨 Lead/
        # 子 Agent web_extract 闭包共享（闭包捕获，不挂 self，避免并行 analyze 互相污染）。
        from competitor_agent.collector.fetch_policy import FetchPolicy

        fetch_policy = FetchPolicy(max_per_run=self._config.collector.fetch_max_per_run)
        # 设计文档 56 M1/M2：Lead 级共享状态——plan 懒绑定 cell + 已核验事实 pinned 清单
        plan_box: dict[str, ReactLoop | None] = {"loop": None}
        pinned_facts: list[str] = []

        def _lead_competitor_now() -> str:
            """competitor 懒绑定：make_plan 落地后经 loop.plan 回填，落地前空串（全局检索）。"""
            loop = plan_box["loop"]
            if loop is not None and loop.plan:
                return str(loop.plan.get("competitor") or "")
            return ""

        def _collect_pinned(rec: dict) -> None:
            pinned_facts.extend(extract_verified_facts(rec))

        def _subagent_loop(name: str, sub_task: str) -> ReactLoop:
            # 记忆/RAG 绑定竞品（设计文档 62 §3.9）：维度子 Agent → Lead 竞品；
            # 候选竞品名 → 候选自身（按竞品名召回复用单竞品记忆，不误绑 Lead 竞品）
            is_dimension = get_subagent_registry().get(name) is not None
            bind_competitor = lead_competitor.name if is_dimension else name
            # 子 Agent 迭代限制已移除（max_steps=None 无限循环，靠 LLM 自然收敛
            # Final Answer；取消经共享 session_id 协作）
            # 主旨2：子 Agent 思考/进度事件过滤（不入 Lead 气泡），诊断事件仍透传
            subagent_sink = _subagent_event_sink(self._event_sink)
            return build_subagent(
                name,
                self._llm or self._default_llm(),
                config=self._config,
                web_extract=self._web_extract_for(bind_competitor, name, fetch_policy),
                extra_tools={
                    # 设计文档 56 M1①：子 Agent kb_recall 按（竞品×维度）绑定
                    "kb_recall": self._build_kb_recall(lambda: bind_competitor, name),
                },
                session_id=session_id,
                memory_context_fn=lambda t: self._memory_ctx_for(bind_competitor, t),
                rag_fn=lambda t: self._rag_ctx_for(bind_competitor, t),
                event_sink=subagent_sink,
                obs_max_chars=self._config.collector.max_content_chars,
                max_steps=None,
                tracer=self._tracer,  # 设计文档 54：子 Agent tool.call span
                max_history_steps=agent_max_history_steps,
                max_parallel_tool_calls=self._max_parallel_tool_calls,
            )

        runner = DelegateRunner(
            runtime_factory=lambda name: SubagentRuntime(
                name=name,
                run=lambda sub_task: _subagent_loop(name, sub_task).run_subagent(sub_task),
            ),
            max_concurrent=max_concurrent,
            timeout_seconds=timeout_seconds,
            tracer=self._tracer,  # 设计文档 54：跨线程 subagent span
        )
        extra_tools: dict[str, Callable[..., str] | ToolSpec] = {
            "make_plan": build_make_plan_tool(allowed_dimensions=self._domain_pack.dimension_names),
            "delegate": make_delegate_tool(
                runner,
                registry=get_subagent_registry(),
                collector=delegate_collector,
                max_candidates=max_candidates,
            ),
            # 设计文档 62 §3.2：候选竞品枚举（DISCOVERY 时 Lead 自调；观察回填驱动 delegate）
            "web_search_candidates": self._web_search_candidates,
            # 设计文档 62 §3.3：Lead 聚合 DISCOVERY/COMPARE 候选结论，产出市场格局核心结论
            "aggregate_report": make_aggregate_tool(),
            # 设计文档 56 M1①：Lead kb_recall（competitor 懒绑定，plan 落地前全局检索）
            "kb_recall": self._build_kb_recall(_lead_competitor_now),
            # 设计文档 70 M3：复用未过期历史维度结果（need_history/补缺维度时 Lead 自调）
            "reuse_dimension_results": reuse_dimension_results,
        }
        if self._config.tools.validate_facts:
            extra_tools["validate_facts"] = build_validate_facts_tool()
        if self._config.tools.detect_conflict:
            extra_tools["detect_conflict"] = build_detect_conflict_tool()
        if self._config.tools.check_freshness:
            extra_tools["check_freshness"] = build_check_freshness_tool(self._check_freshness)
        if self._config.tools.select_source:
            extra_tools["select_source"] = build_select_source_tool(self._select_source)

        dispatcher = build_react_dispatcher(
            config=self._config,
            web_extract=self._lead_web_extract(_lead_competitor_now, fetch_policy),
            exclude=("analyze_competitor",),
            extra_tools=extra_tools,
            tracer=self._tracer,  # 设计文档 54：Lead tool.call span
        )
        agent = ReactAgent(
            llm=self._llm or self._default_llm(),
            dispatcher=dispatcher,
            max_parallel_tool_calls=self._max_parallel_tool_calls,
        )
        # Lead 编排：移除迭代次数限制（max_steps=None 无限循环，靠 LLM 自然收敛 Final
        # Answer 收尾；取消仍经 step_guard 协作）。防失控退化为子 Agent 各自的 max_steps
        # 兜底 + LLM/tool 层超时与硬性安全护栏（url_guard/检查/取消）。
        loop = ReactLoop(
            agent,
            max_steps=None,
            event_sink=self._event_sink,
            session_id=session_id,
            budget=None,
            memory_context_fn=self._host._react_memory_context,
            rag_fn=self._host._react_rag_context,
            obs_max_chars=self._config.collector.max_content_chars,
            system_prompt_override=system_prompt or build_lead_system_prompt(),
            plan_first=plan_first,
            max_history_steps=lead_max_history_steps,
            pinned_facts=pinned_facts,
            on_step=_collect_pinned,
            stream_sink=self._stream_sink,  # 设计文档 63 §5.5：仅 Lead（子 Agent 不传）
            final_as_payload=final_as_payload,  # 设计文档 64 §5.2：对话式分支 False
            history_messages=history_messages,  # 设计文档 65 §3.3：多轮会话历史
            stagnation=StagnationConfig(  # 设计文档 81：停滞检测（自然收敛的客观信号）
                enabled=self._config.agent.stagnation_enabled,
                window=self._config.agent.stagnation_window,
                dup_threshold=self._config.agent.stagnation_dup_threshold,
                sig_repeat=self._config.agent.stagnation_sig_repeat,
                max_hints=self._config.agent.stagnation_max_hints,
                ignore_arg_keys=tuple(self._config.agent.stagnation_ignore_arg_keys),
            ),
        )
        # 收尾 shutdown 用（挂 loop 实例而非 self，避免并行 analyze 互相误杀线程池）
        loop._delegate_runner = runner
        # 设计文档 62 §3.5：候选子 Agent 结构化结果收集器挂 loop，供 comparison 组装器读取
        loop._delegate_collector = delegate_collector
        plan_box["loop"] = loop  # kb_recall/Lead 摄入的 competitor 懒绑定数据源
        return loop

    def _react_competitor(self, task: str) -> Competitor:
        """从任务解析竞品（注册表子串匹配，设计文档 96；未命中退化为裸名 unknown）。"""
        from competitor_agent.core.competitor_registry import match_competitor_from_text

        competitor = match_competitor_from_text(task)
        if competitor is not None:
            return competitor
        return Competitor(name="unknown")

    def _lead_competitor(self, task: str, plan: dict | None) -> Competitor:
        """报告竞品：优先用 plan 的 competitor（注册表命中带官方源），否则从任务解析。"""
        from competitor_agent.core.competitor_registry import resolve_competitor

        name = str((plan or {}).get("competitor") or "").strip()
        if name:
            try:
                competitor = resolve_competitor(name)
                if competitor is not None:
                    return competitor
            except Exception:  # noqa: BLE001 — 注册表解析失败退化为裸名
                logger.debug("注册表解析竞品 %s 失败，退化为裸名", name)
            return Competitor(name=name)
        return self._host._react_competitor(task)

    def _react_memory_context(self, task: str) -> str:
        """Lead 记忆召回（设计文档 35 §3.2 + 62 §3.9）：失败静默降级。

        单竞品（registry）按竞品名召回既有经验；无具体竞品（compare/discovery
        编排）走品类级召回 ``recent_context(competitor="", query=task)``——
        跨竞品按任务语义召回最近会话/摘要，供 Lead 聚合前参考。
        """
        if self._memory is None:
            return ""
        competitor = self._host._react_competitor(task).name
        if competitor and competitor != "unknown":
            return self._memory_ctx_for(competitor, task)
        try:
            return "\n".join(self._memory.recent_context("", top_k=3, query=task))
        except Exception:
            logger.warning("ReAct 品类级记忆召回失败", exc_info=True)
            return ""

    def _react_rag_context(self, task: str) -> str:
        """RAG 检索（与 GapExecutor._retrieve_rag 同口径）：失败静默降级。"""
        if self._retriever is None:
            return ""
        return self._rag_ctx_for(self._host._react_competitor(task).name, task)

    def _rag_ctx_for(self, competitor: str, task: str) -> str:
        """按已知竞品名做 RAG 检索（子 Agent 复用，避免逐子 Agent 重复解析任务）。"""
        if self._retriever is None:
            return ""
        try:
            chunks = self._retriever.retrieve(
                query=task, competitor=competitor, dimension="", top_k=5
            )
        except Exception:  # 检索失败不影响推理
            logger.warning("ReAct RAG 检索失败: %s", competitor, exc_info=True)
            return ""
        if not chunks:
            return ""
        lines = []
        for c in chunks:
            src = f"（来源: {c.source_url}）" if c.source_url else ""
            lines.append(f"- [{c.competitor}/{c.dimension}]{src} {c.text[:300]}")
        return "\n".join(lines)

    def _react_web_extract(self, url: str) -> str:
        """ReAct 工具：真实抓取给定 URL 的页面文本（失败返回可读信息）。

        抓取前过 URL 守卫（设计文档 41）：私网/保留地址拒绝，返回可读原因供回灌自恢复。
        """
        try:
            if self._config.collector.block_private_urls:
                url = guard_http_url(url)
        except URLError as exc:
            return f"URL 被安全守卫拦截: {exc}"
        try:
            obs = self._extractor.fetch(
                InfoGap(field="web"),
                SourceContext(competitor_name="", query="web", kwargs={"url": url}),
            )
        except DataSourceUnavailableError as exc:
            return f"抓取失败: {exc}"
        max_chars = self._config.collector.max_content_chars
        return (obs.raw_text or "").strip()[:max_chars] or "（页面无文本内容）"

    def _web_extract_checked(self, url: str, fetch_policy: Any = None) -> str:
        """per-run 抓取护栏（设计文档 71 §5.3/§6.1）：单跑上限 + 同 URL 去重 + 纯搜索短路。

        - ``fetch_enabled=false``（纯搜索模式）→ 返回固定禁用提示（§2.3/§5.4：ReAct 路径
          同样禁抓，与 MCP web_extract 一致，子 Agent/Lead 均不触网络）；
        - ``fetch_policy`` 为 per-run ``FetchPolicy``（_react_loop 构造，跨 Lead/子 Agent
          共享）：超上限返回「已达上限」提示；同 URL 命中去重回读（不重抓、不计上限）；
        - None → 不设护栏（直接调用，保持现状）。
        """
        if not self._config.collector.fetch_enabled:
            return "抓取层已禁用（FETCH_ENABLED=false）。仅可依赖搜索摘要。"
        if fetch_policy is not None:
            kind, note = fetch_policy.get(url)
            if kind == "limit":
                return note
            if kind == "cached":
                return note
        text = self._host._react_web_extract(url)
        if fetch_policy is not None:
            fetch_policy.record(url, text)
        return text

    def _web_extract_for(
        self,
        competitor: str,
        dimension: str,
        fetch_policy: Any = None,
    ) -> Callable[[str], str]:
        """子 Agent 专用 web_extract：抓取后按（竞品×维度）摄入知识库（RAG 写侧）。

        设计文档 30：分析中采集到的原文即知识库增量，后续分析与追问可检索复用。
        抓取失败的占位文本（守卫拦截/抓取失败）不摄入，避免污染知识库。
        """

        def _extract(url: str) -> str:
            text = self._web_extract_checked(url, fetch_policy)
            self._host._ingest_fetched(competitor, dimension, url, text)
            return text

        return _extract

    def _lead_web_extract(
        self,
        competitor_fn: Callable[[], str],
        fetch_policy: Any = None,
    ) -> Callable[[str], str]:
        """Lead 专用 web_extract（设计文档 56 M1②）：抓取成功后摄入知识库通用域。

        补齐 Lead 摄入缺口（此前只有子 Agent 摄入，Lead 抓的内容取回工具够不到）。
        competitor 懒绑定（make_plan 落地后经 loop.plan 回填），落地前摄入
        ``dimension="web"`` 通用域；守卫拦截/抓取失败/空文本占位不摄入（沿用
        ``_ingest_fetched`` 既有纪律）。闭包按 loop 构造（不挂 self），避免并行
        analyze 互相串 competitor。
        """

        def _extract(url: str) -> str:
            text = self._web_extract_checked(url, fetch_policy)
            self._host._ingest_fetched(competitor_fn(), "web", url, text)
            return text

        return _extract

    def _build_kb_recall(
        self,
        competitor_fn: Callable[[], str],
        dimension: str = "",
    ) -> ToolSpec:
        """kb_recall 闭包工厂（设计文档 56 M1①）：循环内知识库取回工具。

        走 extra_tools（不进 TOOLS/TOOL_SPECS，MCP 工具面零变化）；复用既有
        Retriever 混合检索，零新存储/新依赖。知识库为空/未装配时返回可读信息
        （工具面稳定，不随状态缺 tool）。``competitor_fn`` 懒绑定：Lead 在
        make_plan 落地前以空串全局检索（同竞品优先过滤对空串自然失效）。
        """

        def kb_recall(query: str) -> str:
            if self._retriever is None:
                return "知识库暂无可检索内容（检索器未装配）。"
            try:
                chunks = self._retriever.retrieve(
                    query=str(query), competitor=competitor_fn(), dimension=dimension, top_k=5
                )
            except Exception:
                logger.warning("kb_recall 检索失败", exc_info=True)
                return "知识库检索失败，请改用其他方式获取信息。"
            if not chunks:
                return "知识库暂无可检索内容。"
            lines = []
            for c in chunks:
                src = f"（来源: {c.source_url}）" if c.source_url else ""
                lines.append(f"- [{c.competitor}/{c.dimension}]{src} {c.text[:300]}")
            return "\n".join(lines)[: self._config.collector.max_content_chars]

        return ToolSpec(
            name="kb_recall",
            func=kb_recall,
            description="从知识库取回被折叠步骤的完整内容；仅当需要回溯旧步详情时使用",
            params_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )

    def _ingest_fetched(self, competitor: str, dimension: str, url: str, text: str) -> None:
        """采集原文 → 知识库摄入（幂等：chunk_id 由内容哈希决定）。"""
        if self._ingester is None:
            return
        # 占位/护栏文本不摄入（守卫拦截 / 抓取失败 / 空文本 / 单跑上限提示——doc 71 §5.3）
        if not text or text.startswith(
            ("URL 被安全守卫拦截", "抓取失败", "（页面无文本内容）", "抓取次数已达上限")
        ):
            return
        try:
            self._ingester.ingest(competitor, dimension, text, source_url=url)
        except Exception:  # noqa: BLE001 - 摄入失败不影响采集/分析
            logger.debug("RAG 摄入跳过: %s/%s %s", competitor, dimension, url)

    # ── 复核工具提供方（设计文档 49：代码确定性兜底，不进 LLM 决策）────────

    def _check_freshness(self, competitor: str, dimensions: list[str]) -> dict[str, str]:
        """维度新鲜度判定：读归档年龄（ReportFreshness.dimension_ages）→ {dim: stale/fresh/skip}。"""
        decisions: dict[str, str] = {}
        if self._memory is None:
            return decisions
        try:
            sessions = self._memory.list_sessions(competitor)
            ages: dict[str, float] = {}
            if sessions:
                raw = getattr(sessions[0], "raw", None) or {}
                freshness = ReportFreshness.from_dict(raw.get("freshness"))
                if freshness is not None:
                    ages = dict(freshness.dimension_ages)
        except Exception:
            logger.warning("check_freshness 归档读取失败: %s", competitor, exc_info=True)
            return decisions
        ttl = dict(self._config.freshness.dimension_ttl_days)
        for dim in dimensions:
            age = ages.get(dim)
            if age is None:
                decisions[dim] = "skip"  # 无归档年龄 → 正常采集
            elif age <= float(ttl.get(dim, 30)):
                decisions[dim] = "fresh"
            else:
                decisions[dim] = "stale"
        return decisions

    def _select_source(self, competitor: str, dimension: str) -> list[str]:
        """确定性候选源：注册表 official_links + 常见路径探测（原 SourceSelector 语义）。"""
        from urllib.parse import urlsplit

        from competitor_agent.core.competitor_registry import resolve_competitor

        links: dict[str, str] = {}
        try:
            comp = resolve_competitor(competitor)
            links = dict(comp.official_links or {}) if comp is not None else {}
        except Exception:
            logger.warning("select_source 注册表解析失败: %s", competitor, exc_info=True)
        candidates: list[str] = []
        key = {"pricing": "pricing", "roadmap": "changelog", "feature": "docs"}.get(dimension)
        if key and links.get(key):
            candidates.append(links[key])
        home = links.get("home")
        if home and home not in candidates:
            candidates.append(home)
        # 常见路径探测（确定性）：官方站点按维度拼接，优先级最低
        base = home or (candidates[0] if candidates else "")
        if base:
            try:
                host = urlsplit(base).netloc
                path = {
                    "pricing": "/pricing",
                    "feature": "/features",
                    "roadmap": "/changelog",
                    "ecosystem": "/integrations",
                    "performance": "/benchmarks",
                }.get(dimension)
                if path:
                    candidate = f"https://{host}{path}"
                    if candidate not in candidates:
                        candidates.append(candidate)
            except Exception:  # noqa: BLE001 — 路径探测失败不影响已得候选
                logger.debug("探测 %s 的 %s 路径失败，跳过", base, dimension)
        return candidates

    # ── 记忆写侧（设计文档 49：唯一沉淀点）───────────────────────────────

    def _record_memory_success(self, report: CompetitorReport, transcript: list[dict]) -> None:
        """记忆沉淀（唯一写侧）：每维度取 transcript 首个 URL 源 → skill/outcome/pattern。

        transcript 步（tool/args/result_brief/url）中匹配到该维度或 delegate 批量
        回填的首个 URL 作为来源键（L4 源成功率按 URL 计量）；无则回退报告证据 URL。
        """
        if self._memory is None:
            return
        competitor = report.competitor.name
        for r in report.dimension_results:
            source = self._first_url_for(transcript, r.dimension)
            if not source and r.evidence:
                source = r.evidence[0].url
            if not source:
                continue
            self._memory.record_skill(
                Skill(competitor_name=competitor, gap_field=r.dimension, source_name=source, success=True)
            )
            self._memory.record_outcome(source, True)
            # 设计文档 35：沉淀进化经验（成功模式）
            self._memory.note_pattern(
                competitor,
                r.dimension,
                pattern=f"缺口 {r.dimension} 由源 {source} 有效",
                outcome="success",
            )

    @staticmethod
    def _first_url_for(transcript: list[dict], dimension: str) -> str:
        """transcript 中命中维度的首个 URL，供记忆写侧。

        delegate 批量回填按子结果块切分，避免全部维度都指向首块 URL。
        """
        for step in transcript or []:
            if not isinstance(step, dict):
                continue
            url = str(step.get("url") or "")
            blob = f"{step.get('result_brief') or ''} {step.get('args') or ''}"
            if step.get("tool") == "delegate":
                section = _delegate_section_url(str(step.get("result_brief") or ""), dimension)
                if section:
                    return section
                continue
            if url and dimension in blob:
                return url
        return ""

    def _save_checkpoint_for_resume(
        self, session_id: str, task: str, report: CompetitorReport
    ) -> None:
        """取消时保留 checkpoint（设计文档 14）：未关闭缺口 + 已完成维度，供 /resume 续跑。

        保存失败（磁盘 IO/序列化）不破坏取消保证：记 error 日志后继续返回
        CancelledResult（取消生效优先；checkpoint 丢失非静默，可排障）。
        """
        gaps = [
            InfoGap(field=g.field, priority=g.priority, status=GapStatus.OPEN)
            for g in report.gaps_pending
        ]
        try:
            save_checkpoint(
                session_id=session_id,
                task=task,
                competitor_name=report.competitor.name,
                gaps=gaps,
                dimension_results=report.dimension_results,
                iterations_used=self._budget.iteration_count,
                max_iterations=self._budget.max_iterations,
                sources_tried=[e.url for r in report.dimension_results for e in r.evidence],
            )
        except (OSError, TypeError, ValueError):
            logger.exception(
                "会话 %s 取消后 checkpoint 保存失败，续跑不可用（取消仍生效）",
                session_id,
            )

    # ── team 兼容薄包装（设计文档 49：内部固定流水线删除，保留入口）────────

    def analyze_team(
        self,
        task: str,
        session_id: str | None = None,
        max_retries: int = 1,
    ) -> CompetitorReport:
        """历史兼容入口：委托 analyze()（Lead ReAct 编排，设计文档 49）。

        设计文档 96：意图门控退役——恒产报告（对话语义走 run_conversation()）。
        """
        if max_retries != 1:
            logger.warning("analyze_team 的 max_retries 参数已废弃，忽略")
        return self.analyze(task, session_id=session_id)

    async def analyze_team_async(
        self,
        task: str,
        session_id: str | None = None,
        max_retries: int = 1,
        max_parallel: int = 4,
    ) -> CompetitorReport:
        """历史兼容异步入口：线程池包装 analyze()（签名不变，设计文档 49）。"""
        if max_retries != 1 or max_parallel != 4:
            logger.warning("analyze_team_async 的 max_retries/max_parallel 参数已废弃，忽略")
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.analyze, task, None, "team", session_id)

    # ── M4: 流式分析 ──────────────────────────────────────────────────

    async def analyze_stream(self, task: str, session_id: str | None = None) -> AsyncIterator[ProgressEvent]:
        """流式分析：逐条 yield ProgressEvent（供 Web SSE 消费）"""
        sid = session_id or f"sess_{uuid.uuid4().hex[:8]}"

        yield ProgressEvent(
            event="session_started",
            phase="init",
            message=f"会话 {sid} 已启动",
            payload={"session_id": sid},
        )

        import asyncio

        loop = asyncio.get_running_loop()
        report = await loop.run_in_executor(None, self.analyze, task, None, "team", sid)

        yield ProgressEvent(
            event="report",
            phase="report",
            progress=1.0,
            message=f"报告生成完成，{len(report.dimension_results)} 个维度",
            payload={
                "competitor": report.competitor.name,
                "terminal_state": report.terminal_state,
                "overall_confidence": report.overall_confidence,
            },
        )

        # 归档会话（统一 raw schema，见问题 18）
        if self._memory is not None:
            self._memory.archive_session(
                AnalysisSession(
                    task=task,
                    competitor_name=report.competitor.name,
                    session_id=sid,
                    raw={
                        "markdown_report": report.markdown_report,
                        "terminal_state": report.terminal_state,
                        "dimension_count": len(report.dimension_results),
                        "competitor_name": report.competitor.name,
                        "created_at": report.created_at,
                        "freshness": report.freshness.to_dict() if report.freshness else None,
                        # 设计文档 35：结构化维度 + 遗留缺口，供会话摘要/相关度召回
                        "dimensions": [
                            {"dimension": r.dimension, "summary": r.summary, "confidence": r.confidence}
                            for r in report.dimension_results
                        ],
                        "pending_gaps": [g.field for g in report.gaps_pending],
                    },
                )
            )

    # ── M5: 会话历史 / 对比 / 继续分析 ────────────────────────────────

    def _disambiguate_with_history(
        self,
        task: str,
        conversation_history: list[ChatMessage] | None,
    ) -> str:
        """结合会话历史消歧：上一轮已分析的竞品可作为本轮上下文。

        若任务文本未命中注册表竞品（相对指代如"再对比下 Windsurf"），
        尝试从历史消息中提取最近竞品，拼成可解析的任务文本。
        设计文档 96：竞品命中判定改注册表子串匹配（parse_task 退役，零 LLM）。
        """
        if not conversation_history:
            return task
        from competitor_agent.core.competitor_registry import match_competitor_from_text

        if match_competitor_from_text(task) is not None:
            return task
        last_competitor = self._last_competitor_from_history(conversation_history)
        if last_competitor:
            return f"{task}（承接上文：{last_competitor}）"
        return task

    @staticmethod
    def _last_competitor_from_history(history: list[ChatMessage]) -> str:
        """从历史消息中提取最近提到的竞品规范名"""
        from competitor_agent.core.competitor_registry import COMPETITOR_REGISTRY

        for message in reversed(history):
            content = (message.content or "").lower()
            for canon, competitor in COMPETITOR_REGISTRY.items():
                if canon in content or any(a in content for a in competitor.aliases):
                    return competitor.name
        return ""

    def run(
        self,
        task: str,
        *,
        session_id: str | None = None,
        history_messages: list[dict[str, str]] | None = None,  # 设计文档 65 §3.3：多轮会话历史
    ) -> CompetitorReport | ComparisonReport:
        """直通报告路径（设计文档 96）：CLI/MCP/benchmark/golden 语义——一律产报告。

        对话环入口见 ``run_conversation()``（web 专用）；本方法不再做意图门控
        （设计文档 64 §5 的 parse_task CHAT 门控随 parse_task 退役而删除）。
        全部 resolution 同走一条单 Lead loop，组装按 ``plan.resolution`` 统一分型：
        registry→CompetitorReport、compare/discovery→ComparisonReport。
        """
        task = sanitize_task(task)
        sid = session_id or f"sess_{uuid.uuid4().hex[:8]}"
        return self._run_report_flow(task, sid, history_messages, own_context=True)

    def _run_report_flow(
        self,
        task: str,
        sid: str,
        history_messages: list[dict[str, str]] | None,
        *,
        own_context: bool,
    ) -> CompetitorReport | ComparisonReport:
        """报告流水线主体（设计文档 96）：单 Lead loop → 按 plan 分型组装。

        ``own_context``：True = 独立入口（run()），拥有 trace/session log 生命周期；
        False = generate_report 工具子流程（对话环调用）——复用对话 sid（取消级联/
        共享预算/同一 session log），trace 与 log 收尾归对话环（决策①）。
        """
        set_current_session(sid)
        if own_context:
            self._tracer.start_trace("run", trace_id=sid, input_brief=task)
        try:
            slog = get_session_logger(sid)
            if own_context:
                log_event(slog, "session_started", "init", f"会话 {sid} 启动", task=task)
            self._emit(
                ProgressEvent(
                    event="phase_start",
                    phase="react",
                    message=f"Lead 编排: {task}",
                )
            )
            loop, result = self._host._run_react_loop(task, sid, history_messages)
            plan = loop.plan or {}
            terminal = (
                "cancelled"
                if result.cancelled
                else ("partial" if result.budget_exhausted else "success")
            )
            # 组装按 plan.resolution 统一分型（同一单 Lead loop 产物）
            # 设计文档 65 §2.3：candidate_count 让多候选 DISCOVERY 即使 plan 缺
            # resolution/competitors 也不误判 registry（走单报告路径）
            if self._plan_resolution(plan, candidate_count=len(
                getattr(loop, "_delegate_collector", {}) or {}
            )) in ("compare", "discovery"):
                return self._host._finalize_comparison_report(
                    loop, result, plan, sid, terminal, own_context=own_context
                )
            report = react_report.assemble(
                lead_answer=result.answer,
                competitor=self._lead_competitor(task, plan),
                loop_plan=plan,
                transcript=result.transcript,
                builder=self._builder,
                terminal_state=terminal,
                error_kind=result.error_kind,
            )
            return self._finalize_competitor_report(
                report, task, sid, result.transcript, terminal, own_context=own_context
            )
        except Exception:
            logger.warning("run 会话 %s 异常终止", sid, exc_info=True)
            if own_context:
                self._tracer.end_trace(sid, status="error", output_brief="")
            raise

    def _run_chat(
        self,
        task: str,
        session_id: str | None,
        history_messages: list[dict[str, str]] | None = None,  # 设计文档 65 §3.3
    ) -> ChatResult:
        """对话式分支（设计文档 64 §5.2）：普通提问/闲聊 → 自由 prose 回答，不产报告面板。

        与 ``run()`` 的分析链路相对：不再强制 make_plan（``plan_first=False``）、改用
        对话形态 Lead system prompt（无 PLAN/REPORT schema 约束）、不调用
        ``react_report.assemble`` 与 ``report`` 事件——答案经 Stream 通道
        （``text_delta``/``thinking_delta``）以普通会话消息呈现（无面板/无维度/无置信度）。
        """
        sid = session_id or f"sess_{uuid.uuid4().hex[:8]}"
        set_current_session(sid)
        self._tracer.start_trace("chat", trace_id=sid, input_brief=task)
        try:
            slog = get_session_logger(sid)
            log_event(slog, "session_started", "init", f"会话 {sid} 启动", task=task)
            self._emit(
                ProgressEvent(event="phase_start", phase="react", message=f"对话: {task}")
            )
            loop = self._react_loop(
                task,
                sid,
                system_prompt=build_chat_system_prompt(),
                plan_first=False,
                final_as_payload=False,
                history_messages=history_messages,
            )
            try:
                result = loop.run_with_result(task)
            finally:
                runner = getattr(loop, "_delegate_runner", None)
                if runner is not None:
                    runner.shutdown()
            if result.steps:
                self._budget.record_iteration()
            terminal = (
                "cancelled"
                if result.cancelled
                else ("partial" if result.budget_exhausted else "success")
            )
            close_session_log(sid)
            self._tracer.end_trace(sid, status=terminal, output_brief=result.answer)
            return ChatResult(
                answer=result.answer,
                transcript=result.transcript,
                terminal_state=terminal,
                cancelled=result.cancelled,
                session_id=sid,
            )
        except Exception:
            logger.warning("chat 会话 %s 异常终止", sid, exc_info=True)
            self._tracer.end_trace(sid, status="error", output_brief="")
            raise

    def _latest_report_text(self, competitor: str) -> str:
        """竞品最新归档报告正文（.md 优先，回退 JSON 内嵌 markdown_report）。"""
        from competitor_agent.core.approval_gate import report_json_path
        from competitor_agent.core.report_archiver import _safe_filename, resolve_output_dir

        output_dir = self._config.report.output_dir
        md_path = resolve_output_dir(output_dir) / (_safe_filename(competitor) + ".md")
        if md_path.exists():
            return md_path.read_text(encoding="utf-8")
        json_path = report_json_path(competitor, output_dir)
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
            if isinstance(data, dict) and data.get("markdown_report"):
                return str(data["markdown_report"])
        return ""

    def verify_report(self, competitor: str, mode: str | None = None) -> Any:
        """报告级 NLI 事实校验（设计文档 77 §2.3 产品侧挂点，门面薄路由）。

        对竞品最新归档报告跑 ``NLIVerifier.verify_report``；``verifier.enabled``
        或审批策略 ``verify_before_approve`` 开启时把结果接入审批门——
        contradicted 条目进 rejected 理由、superseded 提示重新分析（reviewer_note）。
        """
        from competitor_agent.collector.fetch_policy import FetchPolicy
        from competitor_agent.core.verifier import NLIVerifier

        report_text = self._latest_report_text(competitor)
        if not report_text:
            raise FileNotFoundError(f"竞品无归档报告可校验: {competitor}")
        vcfg = self._config.verifier
        mode = mode or vcfg.mode
        verifier = NLIVerifier(
            llm=self._llm or self._default_llm(),
            retriever=self._retriever,
            web_extract=self._react_web_extract,
            fetch_policy=FetchPolicy(max_per_run=self._config.collector.fetch_max_per_run),
            timeline=self._timeline,
            alert_sink=self._host._build_alert_sink() if vcfg.enabled else None,
            ingester=self._ingester,
            max_claims=vcfg.max_claims_per_report,
            auto_ingest_superseded=vcfg.auto_ingest_superseded,
        )
        verification = verifier.verify_report(report_text, competitor, mode=mode)
        enforce = vcfg.enabled or self._approval_policy.verify_before_approve
        if enforce:
            self._apply_verification_to_approval(competitor, verification)
        return verification

    def _apply_verification_to_approval(self, competitor: str, verification: Any) -> None:
        """校验结果接入审批门（设计文档 77 §2.3）：contradicted → rejected；
        仅 superseded → 提示「报告含过期信息，建议重新分析」。"""
        from competitor_agent.core.approval_gate import (
            REJECTED,
            report_json_path,
            report_status,
            set_report_status,
        )

        json_path = report_json_path(competitor, self._config.report.output_dir)
        if not json_path.exists():
            return
        reasons = verification.contradicted_reasons()
        current = report_status(json_path)
        if reasons:
            note = "NLI 校验发现 " + str(len(reasons)) + " 处矛盾（真幻觉）：" + "；".join(reasons[:5])
            if current != REJECTED:
                set_report_status(json_path, REJECTED, note)
            return
        if verification.n_superseded:
            set_report_status(
                json_path,
                current,
                "报告含过期信息（superseded " + str(verification.n_superseded) + " 条），建议重新分析",
            )
