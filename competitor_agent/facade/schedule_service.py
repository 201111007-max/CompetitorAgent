"""调度/周报/历史服务（设计文档 78 §2.1）：run_scheduled/weekly/resume/get_history/alerts。

跨服务调用经 ``self._host``（门面）路由：调度轮/续跑/陈旧刷新委派门面
``analyze()``（analysis_service 宿主）；时间线记录委派门面 ``_record_timeline``。
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from competitor_agent.core.alerting import (
    Alert,
    AlertSink,
    build_composite_sink,
)
from competitor_agent.core.alerting import report_diff as _diff_to_alerts
from competitor_agent.core.checkpoint import (
    checkpoint_to_report,
    clear_cancel,
    delete_checkpoint,
    is_cancelled,
    load_checkpoint,
    set_cancel,
)
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import GapStatus, ResultStatus
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.domain_types.freshness import stale_under_ttl
from competitor_agent.domain_types.info_gap import InfoGap, SourceEvidence
from competitor_agent.domain_types.report import (
    CancelledResult,
    ChatResult,
    CompetitorReport,
    DimensionResult,
)
from competitor_agent.facade.assembly import Dependencies, ServiceBase

logger = logging.getLogger("competitor_agent.facade.api")


class ScheduleService(ServiceBase):
    """调度/周报/历史/续跑/告警（doc 78 §2.1；依赖经 ServiceBase 按原私有名展开）。"""

    def __init__(self, deps: Dependencies, host: Any) -> None:
        super().__init__(deps, host)

    def report_diff(self, prev: CompetitorReport, cur: CompetitorReport) -> list[Alert]:
        """两份报告维度级 diff → 竞品异动告警（复用 TimelineMemory.diff 映射为 Alert）。"""
        return _diff_to_alerts(prev, cur)

    def run_scheduled(
        self,
        competitors: list[str] | None = None,
        alert_sink: AlertSink | None = None,
    ) -> list[CompetitorReport]:
        """定时调度轮（设计文档 28 §3.2）：对跟踪竞品执行一次调度轮。

        - 目标竞品：显式传入或归档里的跟踪竞品（去重、跳过对比/发现聚合会话）；
        - 过滤未过期（freshness 内）的竞品，仅重爬过期的；
        - 逐个 analyze（含 JSON 导出），与上次报告 diff 产出异动告警 → AlertSink；
        - 单竞品失败不回滚整体。

        调用时机由外部调度器（cron）控制，本方法只保证"过期才重爬"语义。

        设计文档 67 §2.3.2/§3.3：未显式传 ``alert_sink`` 时按配置组装复合 sink
        （FileAlertSink + webhook 推送 + 可选邮件）；末尾按 ``schedule.weekly_report``
        触发周报聚合（本周变化跨竞品产物）。
        """
        sink = alert_sink or self._build_alert_sink()
        names = list(competitors) if competitors else self._tracked_competitors()
        if not names:
            return []
        ttl = dict(self._config.freshness.dimension_ttl_days)
        refreshed: list[CompetitorReport] = []
        for name in names:
            if not self._stale_for_schedule(name, ttl):
                continue
            # 先取上次快照作 diff 基线，再重爬（analyze 会在 _record_timeline 里覆盖快照）
            prev = self._timeline.report_for(name)
            self._emit(
                ProgressEvent(
                    event="phase_start",
                    phase="schedule",
                    message=f"定时重爬过期竞品: {name}",
                )
            )
            report = self._host.analyze(name, session_id=f"schedule_{uuid.uuid4().hex[:8]}")
            # 定时重爬只处理竞品名（分析类请求），不会走到对话式分支
            assert not isinstance(report, ChatResult)
            refreshed.append(report)
            if prev is not None:
                for alert in self.report_diff(prev, report):
                    sink.emit(alert)
            self._emit(
                ProgressEvent(
                    event="refreshed",
                    phase="schedule",
                    message=f"已刷新 {name}",
                    payload={"competitor": name},
                )
            )
        if refreshed and self._config.schedule.weekly_report:
            try:
                self.build_weekly_report()
            except Exception:
                logger.warning("定时轮末尾周报聚合失败（不影响主流程）", exc_info=True)
        if refreshed and self._config.schedule.refresh_dossiers:
            # 设计文档 82 §2.3：调度轮末尾为当轮竞品刷新档案（默认关，防跟踪期磁盘膨胀）
            for report in refreshed:
                try:
                    self.build_dossier(report.competitor.name)
                except Exception:
                    logger.warning("竞品档案刷新失败（不影响主流程）", exc_info=True)
        return refreshed

    def _build_alert_sink(self) -> AlertSink:
        """按配置组装复合告警 sink（设计文档 67 §3.3）：文件 + webhook + 可选邮件。"""
        return build_composite_sink(
            webhook_urls=self._config.report.alert_webhooks,
            email=dict(self._config.report.alert_email or {}),
        )

    def build_weekly_report(self) -> tuple[Path, Path]:
        """设计文档 67 §2.3.2：跨竞品周报聚合（本周变化），返回 (md, json) 落盘路径。

        数据源：<data_dir>/reports/competitor/*.json + TimelineMemory + 时间窗过滤；
        审批门（§3.2）：含 high-impact 项（价格/榜单/新增竞品）→ 周报 JSON 标
        ``pending_review``，否则 ``approved``。
        """
        from competitor_agent.core.approval_gate import decide_weekly_approval
        from competitor_agent.core.weekly_report import WeeklyReportBuilder

        builder = WeeklyReportBuilder(
            reports_dir=self._config.report.output_dir,
            window_days=self._config.schedule.weekly_window_days,
        )
        data = builder.build()
        data["status"] = (
            decide_weekly_approval(data, self._approval_policy)
            if self._approval_enabled
            else "approved"
        )
        return builder.write(data)

    def _tracked_competitors(self) -> list[str]:
        """归档里的跟踪竞品（每个竞品取最新会话，跳过 " / " 的聚合/对比会话）。"""
        if self._memory is None:
            return []
        latest: dict[str, object] = {}
        for s in self._memory.list_sessions():
            comp = getattr(s, "competitor_name", "")
            if not comp or " / " in comp:
                continue
            if comp not in latest:
                latest[comp] = s
        return list(latest)

    def _stale_for_schedule(self, name: str, ttl: dict[str, int]) -> bool:
        """竞品最新归档会话的 stale 判定：无归档 → 视为需重爬；freshness 内 → 跳过。"""
        if self._memory is None:
            return True
        sessions = self._memory.list_sessions(name)
        if not sessions:
            return True
        raw = getattr(sessions[0], "raw", None) or {}
        return bool(stale_under_ttl(raw, ttl)) or not raw

    def _last_report_for(self, name: str) -> CompetitorReport | None:
        """最近一次时间线快照重建为 CompetitorReport（告警 diff 的 prev；无则 None）。"""
        return self._timeline.report_for(name)

    # ── M4: 中断与断点续跑 ───────────────────────────────────────────

    def cancel(self, session_id: str) -> None:
        """请求取消运行中的分析会话"""
        set_cancel(session_id)
        logger.info("已请求取消会话: %s", session_id)

    def resume(self, session_id: str) -> CompetitorReport:
        """从 checkpoint 恢复：预置已完成维度，未关闭缺口合成 Lead ReAct 续跑任务。"""
        cp = load_checkpoint(session_id)
        if cp is None:
            raise ValueError(f"会话 {session_id} 无 checkpoint，无法恢复")
        # resume 是显式新调用：清除前次取消标志，否则 analyze() 立即判取消、续跑空转
        clear_cancel(session_id)
        logger.info("从 checkpoint 恢复会话: %s (%d gaps)", session_id, len(cp.gaps))

        # 1. 重建竞品与缺口状态（用注册表恢复官方源）
        from competitor_agent.core.competitor_registry import resolve_competitor

        competitor = None
        if cp.competitor_name and cp.competitor_name != "unknown":
            try:
                competitor = resolve_competitor(cp.competitor_name)
            except ValueError:
                from competitor_agent.core.competitor_registry import canonicalize

                competitor = Competitor(name=canonicalize(cp.competitor_name))
        else:
            competitor = Competitor(name=cp.competitor_name)
        gaps = self._reconstruct_gaps_from_checkpoint(cp.gaps)

        # 2. 预置已完成维度（不重跑已关闭缺口）
        completed: list[DimensionResult] = [
            checkpoint_to_report._result_from_dict(r) if hasattr(checkpoint_to_report, '_result_from_dict') else
            DimensionResult(
                dimension=r["dimension"],
                summary=r.get("summary", ""),
                details=r.get("details", {}),
                confidence=r.get("confidence", 0.0),
                evidence=[
                    SourceEvidence(
                        source_name=e["source_name"],
                        url=e.get("url", ""),
                        access_time=e.get("access_time", ""),
                        content_hash=e.get("content_hash", ""),
                        trust_level=e.get("trust_level", 0.5),
                    )
                    for e in r.get("evidence", [])
                ],
                timestamp=r.get("timestamp", ""),
                status=ResultStatus(r.get("status", "partial")),
            )
            for r in cp.dimension_results
        ]

        # 3. 未关闭缺口 → 合成 Lead ReAct 续跑任务（已完成维度由 checkpoint 预置）
        open_gaps = [g for g in gaps if not g.is_closed]
        if open_gaps:
            task = self._resume_task(cp.task, [g.field for g in open_gaps])
            resumed = self._host.analyze(task, session_id=session_id)
            # resume 从 checkpoint 续跑（竞品分析任务），不会走到对话式分支
            assert not isinstance(resumed, ChatResult)
            by_dim = {r.dimension: r for r in completed}
            for r in resumed.dimension_results:
                by_dim[r.dimension] = r
            results = list(by_dim.values())
            # 续跑后仍未产出的缺口（交集）留作 pending
            produced = {r.dimension for r in results}
            pending = [
                g for g in resumed.gaps_pending
                if g.field not in produced and g.field in {og.field for og in open_gaps}
            ]
            terminal = resumed.terminal_state
        else:
            results = completed
            pending = []
            terminal = "success"
            delete_checkpoint(session_id)

        report = self._builder.build(
            competitor=competitor,
            results=results,
            gaps_pending=pending,
            terminal_state=terminal,
        )

        if is_cancelled(session_id):
            logger.info("会话 %s 续跑中再次取消，返回部分结果", session_id)
            self._emit(ProgressEvent(event="cancelled", phase="report", message="续跑已取消"))
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

        self._host._record_timeline(report)
        self._emit(ProgressEvent(event="report", phase="report", progress=1.0, message="续跑完成"))
        return report

    @staticmethod
    def _resume_task(base_task: str, dimensions: list[str]) -> str:
        """把待续跑维度声明进任务文本，供 Lead 重排（已完成维度由 checkpoint 预置）。"""
        dim_text = "、".join(dimensions) or "全部维度"
        return f"{base_task}（续跑：请补齐维度 {dim_text}，已完成维度直接复用）"

    @staticmethod
    def _reconstruct_gaps_from_checkpoint(gaps_data: list[dict]) -> list[InfoGap]:
        """从 checkpoint gap 字典列表重建 InfoGap 对象（保留 status/confidence/evidence）。"""
        gaps = []
        for g in gaps_data:
            gap = InfoGap(
                field=g["field"],
                priority=g.get("priority", 5),
                confidence=g.get("confidence", 0.0),
                sources_tried=g.get("sources_tried", []),
                status=GapStatus(g.get("status", "open")),
            )
            for ev in g.get("evidence", []):
                gap.add_evidence(
                    SourceEvidence(
                        source_name=ev.get("source_name", ""),
                        url=ev.get("url", ""),
                        content_hash=ev.get("content_hash", ""),
                        trust_level=ev.get("trust_level", 0.5),
                    )
                )
            gaps.append(gap)
        return gaps

    # ── M4: 历史查询 ──────────────────────────────────────────────────

    def get_history(self, competitor: str | None = None) -> list[CompetitorReport]:
        """查询历史分析报告

        Args:
            competitor: 竞品名称（可选，留空返回全部）
        Returns:
            历史报告列表
        """
        if self._memory is None:
            return []

        sessions = self._memory.list_sessions(competitor)

        reports: list[CompetitorReport] = []
        for s in sessions:
            raw = s.raw if hasattr(s, "raw") else {}
            reports.append(
                CompetitorReport(
                    competitor=Competitor(name=s.competitor_name),
                    markdown_report=str(raw.get("markdown_report", "")),
                    terminal_state=str(raw.get("terminal_state", "")),
                    created_at=s.created_at,
                )
            )
        return reports

    def continue_analysis(self, session_id: str) -> CompetitorReport:
        """恢复未完成的会话（对齐 hermes -c/--continue 语义）"""
        return self.resume(session_id)

    def build_dossier(self, competitor: str, window_days: int | None = None) -> Any:
        """单竞品档案导出（设计文档 82 §2.3 门面薄路由）：纯本地聚合零新采集。

        返回 (md_path, json_path)；数据源 = 归档报告 + 时间线 + 知识库证据。
        """
        from competitor_agent.core.dossier import DossierBuilder

        builder = DossierBuilder(
            reports_dir=self._config.report.output_dir,
            data_dir=self._timeline.data_dir,
            timeline=self._timeline,
            store=self._store,
        )
        dossier = builder.build(competitor, window_days=window_days)
        return builder.write(dossier)

    def refresh_stale(
        self,
        ttl_override: dict[str, int] | None = None,
        recompute_all: bool = False,
    ) -> list[CompetitorReport]:
        """陈旧度检测 + 定时重爬（设计文档 26 §3.3）。

        扫描记忆/存档中每个竞品的最新会话，按维度 TTL 判定过期后重分析。
        逐竞品分析走 run()/analyze（并行归 Lead delegate）；单竞品失败不回滚整体。

        Args:
            ttl_override: 覆盖默认维度 TTL（天），None 用 config.freshness。
            recompute_all: True 时无视新鲜度，全部竞品重新分析（CLI --all）。
        Returns:
            刷新后的报告列表。
        """
        if self._memory is None:
            return []
        ttl = dict(self._config.freshness.dimension_ttl_days)
        if ttl_override:
            ttl.update(ttl_override)
        if not recompute_all and not self._config.freshness.refresh_check_enabled:
            return []

        # 每个竞品只取最新会话（list_sessions 已按 created_at 降序）
        latest: dict[str, object] = {}
        for s in self._memory.list_sessions():
            comp = getattr(s, "competitor_name", "")
            if not comp or " / " in comp:
                continue  # 跳过对比/发现的聚合会话
            if comp not in latest:
                latest[comp] = s

        refreshed: list[CompetitorReport] = []
        for comp, session in latest.items():
            stale = stale_under_ttl(getattr(session, "raw", None) or {}, ttl) if not recompute_all else []
            if not recompute_all and not stale:
                continue
            report = self._host.analyze(comp, session_id=f"refresh_{uuid.uuid4().hex[:8]}")
            # 定时刷新只处理竞品名（分析类请求），不会走到对话式分支
            assert not isinstance(report, ChatResult)
            refreshed.append(report)
            self._emit(
                ProgressEvent(
                    event="refreshed",
                    phase="refresh",
                    message=f"已刷新 {comp}",
                    payload={"competitor": comp, "stale_dimensions": stale or None},
                )
            )
        return refreshed
