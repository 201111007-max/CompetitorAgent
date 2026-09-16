"""对比/发现服务（设计文档 78 §2.1）：compare/discover 路由 + comparison 组装。

跨服务调用经 ``self._host``（门面）路由：compare/discover 委派门面 ``run()``
（doc 62 §3.5 统一入口语义不变）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

from competitor_agent.agent.react_loop import ReactLoop, ReactRunResult
from competitor_agent.core.report_exporter import export_comparison_json
from competitor_agent.core.task_parser import parse_task
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.domain_types.report import ComparisonReport
from competitor_agent.facade.assembly import Dependencies, ServiceBase
from competitor_agent.observability.logger import close_session_log

logger = logging.getLogger("competitor_agent.facade.api")


class CompareService(ServiceBase):
    """compare/discover/aggregate 路由 + comparison 组装（doc 78 §2.1）。"""

    def __init__(self, deps: Dependencies, host: Any) -> None:
        super().__init__(deps, host)

    def discover(self, task: str) -> ComparisonReport:
        """兼容保留（设计文档 62 §3.5）：= run(task) 的 DISCOVERY 语义路径（deprecated 告警）。"""
        logger.warning("discover() 已废弃（历史兼容）：请改用 run() 统一入口")
        return cast(ComparisonReport, self._host.run(task))

    def _finalize_comparison_report(
        self,
        loop: ReactLoop,
        result: ReactRunResult,
        plan: dict[str, Any],
        sid: str,
        terminal: str,
    ) -> ComparisonReport:
        """compare/discovery 组装 + 收尾（矩阵 + 结论段 + 导出 + 事件/trace）。

        候选子 Agent 的 ``dimensions[]``（delegate 收集器）→ 每候选最小 CompetitorReport →
        ``build_comparison`` 矩阵（执行层）；Lead Final Answer 的结论段拼入。
        """
        from competitor_agent.facade.comparison_report import assemble_comparison

        report = assemble_comparison(
            lead_answer=result.answer,
            plan=plan,
            candidate_results=getattr(loop, "_delegate_collector", {}) or {},
            builder=self._builder,
            terminal_state=terminal,
        )
        self._export_comparison_json(report)
        close_session_log(sid)
        self._emit(
            ProgressEvent(
                event="report",
                phase="report",
                progress=1.0,
                message=f"报告生成完成，终态={terminal}",
            )
        )
        self._tracer.end_trace(sid, status=terminal, output_brief=report.markdown_report)
        return report

    def _export_comparison_json(self, report: ComparisonReport) -> Path | None:
        """设计文档 28 §8.2 D2a：比较报告导出 output/comparison/<names>.json（品类矩阵）。"""
        if not self._config.report.export_json:
            return None
        if not report.competitors:
            # 设计文档 73 §3.4 + D1 方案 A：普查/零候选不落空壳矩阵 compare.json
            # （避免「competitors:[] / matrix:[]」空壳误导前端与下载方）
            logger.info("零候选对比报告跳过空壳矩阵导出（设计文档 73 §3.4 D1 方案 A）")
            return None
        try:
            # 设计文档 70 §8.2：默认 → resolve_comparison_dir()（output/comparison），不再用 comparison_dir
            path = export_comparison_json(report)
        except Exception:
            logger.warning("对比矩阵 JSON 导出失败: ", exc_info=True)
            return None
        try:
            note = f"\n> 结构化矩阵已导出: `{path}`\n"
            if report.markdown_report and note.strip() not in report.markdown_report:
                report.markdown_report = report.markdown_report.rstrip() + "\n" + note
        except Exception:
            logger.warning("对比矩阵 JSON 导出提示追加失败: %s", report.competitors, exc_info=True)
        return path

    def compare(self, *competitors: str) -> ComparisonReport:
        """兼容保留（设计文档 62 §3.5）：= run(task) 的 COMPARE 语义路径（deprecated 告警）。

        兼容旧签名 compare(a, b=None)：单个参数会被解析（"对比 A 和 B" / "A vs B"）；
        多个参数逐个作为竞品名处理；最终统一委托 run()（单 Lead loop）执行。
        """
        logger.warning("compare() 已废弃（历史兼容）：请改用 run() 统一入口")
        names: list[str] = []
        if len(competitors) == 1:
            parsed = parse_task(competitors[0], llm=self._llm, use_llm=self._use_llm)
            names = list(parsed.competitors)
        else:
            for c in competitors:
                parsed = parse_task(c, llm=self._llm, use_llm=self._use_llm)
                primary = parsed.primary_competitor
                if primary and primary != "unknown" and primary not in names:
                    names.append(primary)
        if len(names) < 2:
            raise ValueError("对比需要两个及以上竞品（或用 /compare A 和 B）")
        return cast(ComparisonReport, self._host.run(f"对比 {' 和 '.join(names)}"))

    @staticmethod
    def _task_with_sources(competitor: Competitor) -> str:
        """把发现竞品的 official_links 注入任务文本，使 Lead 拿到官方源。

        复用 parse_task 的 custom_sources 提取（"官网是 …"/"定价页是 …"），
        避免发现出的未知竞品因无官方源而 0 候选 → 0 维度。
        """
        parts = [f"分析 {competitor.name}"]
        label = {"home": "官网是", "pricing": "定价页是", "docs": "文档是", "changelog": "更新日志是"}
        for key, text in label.items():
            url = competitor.official_links.get(key)
            if url:
                parts.append(f"{text} {url}")
        return "，".join(parts)
