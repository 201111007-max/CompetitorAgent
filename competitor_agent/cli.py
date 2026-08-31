"""CLI 入口（competitor_agent/cli.py）— M5.1

对照 usage.md 已承诺接口补齐实现：
    python -m competitor_agent.cli analyze "Claude Code" [--out DIR]
    python -m competitor_agent.cli analyze "对比 Cursor 和 Windsurf"
    python -m competitor_agent.cli history [--competitor cursor]
    python -m competitor_agent.cli benchmark
    python -m competitor_agent.cli -z "分析 Cursor"      # oneshot
    python -m competitor_agent.cli -c session_id          # 恢复会话

无子命令时进入交互 REPL（input()），支持斜杠命令（/analyze /compare /history
/resume /benchmark /help），非命令文本走 浅清洗 → 任务解析 → API 执行。
"""
from __future__ import annotations

import argparse
import sys
from typing import NoReturn

from competitor_agent.config.loader import AppConfig, load_config
from competitor_agent.core.command_registry import command_dispatch
from competitor_agent.core.input_sanitizer import sanitize_task
from competitor_agent.core.task_parser import parse_task
from competitor_agent.domain_types.report import ChatResult, ComparisonReport, CompetitorReport
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.llm.client import LLMClient
from competitor_agent.observability.logger import setup_logging
from competitor_agent.secret_vault import get_data_dir, get_reports_dir

PROMPT = "competitor> "


def _build_llm(cfg: AppConfig) -> LLMClient:
    """按 LLMConfig 构造带重试/fallback/超时的 LLMClient（设计文档 36/46）"""
    from competitor_agent.observability.tracer import get_tracer

    return LLMClient(
        model=cfg.llm.model,
        base_url=cfg.llm.api_base_url,
        fallback_models=cfg.llm.fallback_models,
        timeout=cfg.llm.timeout,
        max_retries=cfg.llm.max_retries,
        pricing_per_1k=cfg.llm.pricing_per_1k,
        tracer=get_tracer(),  # 设计文档 54：generation span（LLM 调用挂到当前 trace）
    )


def _make_api(engine: str = "react") -> CompetitorAnalysisAPI:
    cfg = load_config()
    return CompetitorAnalysisAPI(
        llm=_build_llm(cfg), use_llm=True, config=cfg, engine=engine
    )


def _print_report(report: CompetitorReport) -> None:
    print(report.markdown_report)
    if report.gaps_pending:
        print(f"\n[提示] {len(report.gaps_pending)} 个缺口未关闭，可用 /resume 继续。")


def _run_analyze(
    api: CompetitorAnalysisAPI,
    args: str,
    out_dir: str | None = None,
    mode: str = "team",
    llm: LLMClient | None = None,
    use_llm: bool = True,
) -> int:
    """analyze 子命令 + /analyze 处理器

    use_llm 默认 True：与库入口（facade/api.py）默认一致（设计文档 46 §3.3）。
    设计文档 47：仅 LLM 解析/规划/分析；无 Key → 打印"需要配置 LLM API Key"退出码 2。
    """
    args = sanitize_task(args.strip())
    if not args:
        print("用法: analyze <竞品或任务>")
        return 0
    try:
        # LLM 可用性守卫（设计文档 47：无 Key → 退出码 2）；解析失败即短路
        parse_task(args, llm=llm, use_llm=use_llm)
    except LLMUnavailableError as exc:
        print(f"需要配置 LLM API Key 才能分析（LLM 不可用: {exc}）")
        return 2
    # 设计文档 62 §3.7：分派收敛到统一 run()（DISCOVERY/COMPARE/单竞品由库内路由）
    # 设计文档 64 §5：run() 意图门控可返回 ChatResult（普通提问 → 直接打印对话答案）
    report = api.run(args)
    if isinstance(report, ChatResult):
        markdown = report.answer or ""
        print(markdown or "（无回答）")
        name = "chat"
    elif isinstance(report, ComparisonReport):
        markdown = report.markdown_report
        print(markdown)
        name = "compare"
    else:
        _print_report(report)
        markdown = report.markdown_report
        name = report.competitor.name
    if out_dir:
        _save_markdown(markdown, name, out_dir)
    return 0


def _save_markdown(text: str, name: str, out_dir: str) -> None:
    import os

    os.makedirs(out_dir, exist_ok=True)
    safe = name.replace("/", "_") or "report"
    path = os.path.join(out_dir, f"{safe}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[已保存] {path}")


def _run_history(api: CompetitorAnalysisAPI, args: str) -> None:
    competitor = None
    if "--competitor" in args:
        competitor = args.split("--competitor", 1)[1].strip().split()[0] if args.strip() else None
    reports = api.get_history(competitor)
    if not reports:
        print("（无历史记录）")
        return
    for r in reports:
        print(f"- {r.competitor.name} | {r.terminal_state} | {r.created_at}")


def _run_refresh(api: CompetitorAnalysisAPI, args: str) -> None:
    """refresh [--stale|--all]：陈旧度检测重爬（设计文档 26 §3.3）。"""
    lowered = (args or "").lower()
    recompute_all = "--all" in lowered or "-a" in lowered
    if recompute_all:
        reports = api.refresh_stale(recompute_all=True)
        print(f"已重爬全部 {len(reports)} 个竞品")
    else:
        reports = api.refresh_stale()
        print(f"已刷新 {len(reports)} 个过期竞品报告")
    for r in reports:
        print(f"- {r.competitor.name} | 终态={r.terminal_state} | {len(r.dimension_results)} 维度")


def _run_timeline(api: CompetitorAnalysisAPI, args: str) -> None:
    """timeline <competitor>：查看竞品时间线事件（设计文档 26 §3.4）。"""
    competitor = args.strip()
    if not competitor:
        print("用法: timeline <competitor>")
        return
    events = api.timeline.events(competitor)
    if not events:
        print(f"（{competitor} 暂无时间线事件，可先 analyze 该竞品）")
        return
    print(f"# {competitor} 竞品时间线")
    for e in events:
        date = str(getattr(e, "occurred_at", ""))[:10] or "-"
        print(f"- [{date}] {e.event_type}: {e.summary}")
        urls = getattr(e, "evidence_urls", None) or []
        if urls:
            print(f"  证据: {', '.join(str(u) for u in urls[:2])}")


def _run_schedule(api: CompetitorAnalysisAPI, args: str) -> None:
    """schedule [--competitors a,b]：定时调度轮（设计文档 28 §3.2）。

    只重爬过期（超过维度 TTL）竞品，产出含结构化 JSON 报告 + 异动告警文件。
    """
    from competitor_agent.core.alerting import FileAlertSink

    competitors = None
    if args and args.strip():
        competitors = [p.strip() for p in args.split(",") if p.strip()]
    sink = FileAlertSink()
    reports = api.run_scheduled(competitors=competitors, alert_sink=sink)
    if not reports:
        print("（无过期竞品需重爬，或尚无跟踪竞品）")
        return
    print(f"定时调度完成：重爬 {len(reports)} 个过期竞品")
    for r in reports:
        print(f"- {r.competitor.name} | 终态={r.terminal_state} | {len(r.dimension_results)} 维度")


def _run_weekly(api: CompetitorAnalysisAPI, args: str) -> None:
    """weekly：跨竞品周报聚合（设计文档 67 §2.3.2），打印落盘路径。"""
    try:
        md_path, json_path = api.build_weekly_report()
    except Exception as exc:  # noqa: BLE001
        print(f"周报生成失败: {exc}")
        return
    print(f"周报已生成（Markdown）: {md_path}")
    print(f"周报已生成（JSON）: {json_path}")
    if md_path.exists():
        print("\n".join(md_path.read_text(encoding="utf-8").splitlines()[:40]))


def _run_report(api: CompetitorAnalysisAPI, args: str) -> None:
    """report：审批（--status/--approve/--reject）+ 可视化导出（--html/--visual）。

    用法:
        report --status <name>
        report --approve <name> [--note "..."]
        report --reject <name> --note "..."
        report --html <name>
        report --visual <name>       # 需对比报告（多竞品）
    """
    import json as _json

    from competitor_agent.core.approval_gate import (
        report_json_path,
        report_status,
        set_report_status,
    )
    from competitor_agent.core.report_archiver import report_file_path

    tokens = args.split()
    if not tokens:
        print("用法: report --status/--approve/--reject/--html/--visual <name> [--note ...]")
        return
    if "--approve" in tokens or "--reject" in tokens:
        is_approve = "--approve" in tokens
        marker = "--approve" if is_approve else "--reject"
        idx = tokens.index(marker)
        if idx + 1 >= len(tokens):
            print(f"用法: report {marker} <name>")
            return
        name = tokens[idx + 1]
        note = ""
        if "--note" in tokens:
            ni = tokens.index("--note")
            note = " ".join(tokens[ni + 1 :])
        path = report_json_path(name)
        if not path.exists():
            print(f"报告 JSON 不存在: {path}（需先 export_json 且已分析过 {name}）")
            return
        set_report_status(path, "approved" if is_approve else "rejected", reviewer_note=note)
        print(f"[{'已审批通过' if is_approve else '已驳回'}] {name} → {path}")
        return
    if "--status" in tokens:
        idx = tokens.index("--status")
        if idx + 1 >= len(tokens):
            print("用法: report --status <name>")
            return
        name = tokens[idx + 1]
        path = report_json_path(name)
        print(f"{name}: {report_status(path)}（{path}）")
        return
    if "--html" in tokens:
        from competitor_agent.core.report_visuals import render_html_doc

        idx = tokens.index("--html")
        if idx + 1 >= len(tokens):
            print("用法: report --html <name>")
            return
        name = tokens[idx + 1]
        md_path = report_file_path(name)
        json_path = report_json_path(name)
        if not md_path.exists() or not json_path.exists():
            print(f"报告缺失（需 .md 与 .json 均在落盘目录）: {name}")
            return
        structured = _json.loads(json_path.read_text(encoding="utf-8"))
        created = str(structured.get("created_at") or "")
        html_path = render_html_doc(
            md_path.read_text(encoding="utf-8"),
            structured,
            title=name,
            created_at=created,
            out_path=str(md_path.with_suffix(".html")),
        )
        print(f"HTML 已导出: {html_path}")
        return
    if "--visual" in tokens:
        from competitor_agent.core.report_visuals import render_radar

        idx = tokens.index("--visual")
        if idx + 1 >= len(tokens):
            print("用法: report --visual <name>")
            return
        name = tokens[idx + 1]
        json_path = report_json_path(name)
        if not json_path.exists():
            print(f"报告 JSON 不存在: {json_path}")
            return
        data = _json.loads(json_path.read_text(encoding="utf-8"))
        if "competitors" not in data or not data.get("competitors"):
            print("雷达图仅支持对比报告（多竞品）；单竞品请用 --html 导出。")
            return
        comparison = _comparison_from_json(data)
        radar_path = render_radar(comparison)
        print(f"雷达图已导出: {radar_path}" if radar_path else "雷达图跳过（matplotlib 未安装，可用 pip install \".[visuals]\"）")
        return
    print("未知 report 操作（可选 --status/--approve/--reject/--html/--visual）")


def _comparison_from_json(data: dict) -> ComparisonReport:
    """从对比报告 JSON 重建 ComparisonReport（供雷达图渲染，数据来自 matrix）。"""
    from competitor_agent.domain_types.competitor import Competitor
    from competitor_agent.domain_types.enums import ResultStatus
    from competitor_agent.domain_types.report import (
        ComparisonReport,
        CompetitorReport,
        DimensionResult,
    )

    names = [str(n) for n in data.get("competitors") or []]
    dims_by_comp: dict[str, dict[str, float]] = {n: {} for n in names}
    for row in data.get("matrix") or []:
        dim = str(row.get("dimension") or "")
        values = row.get("values") or {}
        for n in names:
            conf = values.get(n)
            if conf is not None:
                dims_by_comp[n][dim] = float(conf)
    reports = [
        CompetitorReport(
            competitor=Competitor(name=n),
            dimension_results=[
                DimensionResult(
                    dimension=d,
                    confidence=c,
                    summary="",
                    status=ResultStatus.COMPLETE if c else ResultStatus.UNAVAILABLE,
                )
                for d, c in dims.items()
            ],
        )
        for n, dims in dims_by_comp.items()
    ]
    return ComparisonReport(competitors=[Competitor(name=n) for n in names], reports=reports)


def _run_schedule_daemon(api: CompetitorAnalysisAPI) -> int:
    """schedule --daemon：前台运行内置调度器（设计文档 67 §2.3.1）。"""
    from competitor_agent.core.scheduler import WeeklyScheduler

    cfg = load_config().schedule
    scheduler = WeeklyScheduler(
        lambda: api.run_scheduled(),
        interval_hours=cfg.interval_hours,
        cron_expr=cfg.cron_expr,
    )
    print(
        "调度器启动（Ctrl+C 退出）: "
        + (f"cron={cfg.cron_expr!r}" if cfg.cron_expr else f"interval={cfg.interval_hours:g}h")
    )
    scheduler.start()
    try:
        import time as _time

        while True:
            _time.sleep(1)
    except KeyboardInterrupt:
        print("\n调度器已停止。")
        return 0
    finally:
        scheduler.stop()


def _run_resume(api: CompetitorAnalysisAPI, args: str) -> None:
    session_id = args.strip()
    if not session_id:
        from competitor_agent.core.checkpoint import list_checkpoints

        cps = list_checkpoints()
        if not cps:
            print("（无可用 checkpoint）")
            return
        session_id = cps[0].session_id
        print(f"恢复最近会话: {session_id}")
    report = api.continue_analysis(session_id)
    _print_report(report)


def _run_benchmark(args: str) -> None:
    from competitor_agent.evaluation.benchmark import main as benchmark_main

    tokens = args.split()
    ablate = "--ablate" in tokens
    tokens = [t for t in tokens if t != "--ablate"]
    # 设计文档 37：透传 --llm/--tag/--cost-limit 给 evaluation.benchmark.main
    exit_code = benchmark_main(tokens)
    if ablate:
        # 设计文档 30：消融/对比实验——5 组变体全跑 + 落盘 <data_dir>/reports/ablation/
        from competitor_agent.evaluation.ablation import (
            AblationRunner,
            render_ablation_table,
            write_ablation_report,
        )

        results = AblationRunner().run()
        paths = write_ablation_report(results, get_reports_dir() / "ablation")
        print(render_ablation_table(results))
        for p in paths:
            print(f"ablation: {p}")
    if exit_code:
        raise SystemExit(exit_code)


def _run_rag_warmup() -> int:
    """rag-warmup：显式下载/校验嵌入模型缓存并打印向量层状态（设计文档 52 §2.2）。

    唯一触网路径，须用户显式执行；available → 0，degraded/下载失败 → 1。
    """
    from competitor_agent.knowledge_base.vector_store import warmup_status

    status = warmup_status()
    print(f"嵌入模型: {status['model_name']}")
    print(f"chromadb 版本: {status['chromadb_version'] or '未安装'}")
    if status["model_path"]:
        print(f"模型缓存: {status['model_path']}")
    if status["downloaded"]:
        print("模型已下载完成并校验可用。")
    if status["available"]:
        print("向量层状态: available（语义嵌入就绪）")
        return 0
    print("向量层状态: degraded（模型未缓存，记忆召回/检索降级词袋）")
    if status["error"]:
        print(f"模型下载失败: {status['error']}")
    return 1


def _run_trace(action: str, sid: str | None) -> int:
    """trace list / trace show <sid>：链路追踪查看器（设计文档 54 Q3）。"""
    from competitor_agent.observability import tracer as T

    if action == "list":
        sums = T.list_summaries()
        if not sums:
            print("（暂无 trace 记录；先 analyze 一次生成 <data_dir>/traces）")
            return 0
        header = f"{'TRACE_ID':<26}{'NAME':<12}{'STATUS':<9}{'SPANS':>6}{'TOKENS':>8}{'$COST':>10}  TASK"
        print(header)
        for s in sums:
            cost = float(s.get("total_cost_usd") or 0.0)
            tok = int(s.get("total_tokens") or 0)
            span_count = int(s.get("span_count") or 0)
            tid = str(s.get("trace_id") or "")
            task = str(s.get("input_brief") or "")[:40]
            print(f"{tid[:26]:<26}{s.get('name') or ''!s:<12}{s.get('status') or ''!s:<9}"
                  f"{span_count:>6}{tok:>8}{cost:>10.4f}  {task}")
        return 0

    if not sid:
        print("用法: trace show <session_id>")
        return 0
    spans = T.load_trace(sid)
    if not spans:
        print(f"（trace {sid} 无记录——先 analyze 一次再查看；或检查 trace_id 是否即 session_id）")
        return 0
    print(T.render_waterfall(spans))
    total_cost = sum(float(r.get("cost_usd") or 0.0) for r in spans if r.get("kind") == "llm")
    total_tokens = sum(int(r.get("total_tokens") or 0) for r in spans if r.get("kind") == "llm")
    print(f"聚合：{len(spans)} 条 span | {total_tokens} tokens | ${total_cost:.4f}")
    return 0


def _run_help(args: str) -> None:
    from competitor_agent.core.command_registry import COMMAND_REGISTRY

    target = args.strip().lstrip("/").lower()
    if target:
        for cmd in COMMAND_REGISTRY:
            if cmd.name == target or target in cmd.aliases:
                print(f"/{cmd.name} {cmd.args_hint}".rstrip())
                return
        print(f"未知命令: /{target}")
        return
    print("可用命令:")
    for cmd in COMMAND_REGISTRY:
        print(f"  /{cmd.name:9s} {cmd.args_hint}")


def _run_analyze_repl(
    api: CompetitorAnalysisAPI,
    args: str,
    llm: LLMClient | None = None,
    use_llm: bool = True,
) -> None:
    """REPL 版 analyze：丢弃退出码（交互循环不因无 Key 退出）。"""
    _run_analyze(api, args, llm=llm, use_llm=use_llm)


def _repl(api: CompetitorAnalysisAPI, llm: LLMClient | None = None, use_llm: bool = True) -> NoReturn:
    """交互 REPL：斜杠命令路由 + 自由文本任务（use_llm 默认 True，与库语义一致）"""
    print("competitor_agent 交互模式（输入 /help 查看命令，Ctrl+C / Ctrl+D 退出）")
    handlers = {
        "analyze": lambda a: _run_analyze_repl(api, a, llm=llm, use_llm=use_llm),
        "compare": lambda a: _run_compare_repl(api, a),
        "history": lambda a: _run_history(api, a),
        "resume": lambda a: _run_resume(api, a),
        "refresh": lambda a: _run_refresh(api, a),
        "timeline": lambda a: _run_timeline(api, a),
        "schedule": lambda a: _run_schedule(api, a),
        "weekly": lambda a: _run_weekly(api, a),
        "report": lambda a: _run_report(api, a),
        "benchmark": lambda a: _run_benchmark(a),
        "help": lambda a: _run_help(a),
    }
    while True:
        try:
            line = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            sys.exit(0)
        if not line:
            continue
        if line in ("exit", "quit"):
            sys.exit(0)
        handled = command_dispatch(line, handlers)
        if handled:
            continue
        _run_analyze(api, line, llm=llm, use_llm=use_llm)


def _run_compare_repl(api: CompetitorAnalysisAPI, args: str) -> None:
    """/compare A 和 B 或 /compare A B"""
    args = args.strip()
    if not args:
        print("用法: /compare A 和 B")
        return
    parts = [p.strip() for p in args.replace(" 和 ", " ").split() if p.strip()]
    if len(parts) < 2:
        print("用法: /compare A 和 B")
        return
    # 设计文档 62 §3.7：统一入口 run()（COMPARE 语义由库内路由）
    # 设计文档 64 §5：普通提问 → ChatResult（直接打印对话答案）
    report = api.run(f"对比 {parts[0]} 和 {parts[1]}")
    if isinstance(report, ChatResult):
        print(report.answer or "")
        return
    print(report.markdown_report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="competitor_agent",
        description="竞品分析 Agent CLI",
    )
    parser.add_argument("-z", "--oneshot", dest="oneshot", default=None, help="单发任务（脚本化）")
    parser.add_argument("-c", "--continue", dest="resume_id", default=None, help="恢复指定会话")
    sub = parser.add_subparsers(dest="command")

    analyze_p = sub.add_parser("analyze", help="单竞品/对比分析")
    analyze_p.add_argument("task", nargs="+", help="竞品名或分析任务")
    analyze_p.add_argument("--out", dest="out_dir", default=None, help="报告输出目录")
    analyze_p.add_argument("--mode", default="team", choices=["single", "team"], help="[已废弃] 历史参数，统一走 Lead ReAct 编排（设计文档 49）")
    analyze_p.add_argument("--engine", default="react", choices=["react", "langgraph"], help="编排引擎：react=自研 Lead ReAct（默认），langgraph=LangGraph StateGraph（设计文档 51，需 .[langgraph]）")

    history_p = sub.add_parser("history", help="查询历史分析记录")
    history_p.add_argument("--competitor", default=None, help="按竞品过滤")

    refresh_p = sub.add_parser("refresh", help="陈旧度检测/定时重爬过期竞品报告（设计文档 26）")
    refresh_p.add_argument("--stale", action="store_true", help="仅刷新超过维度 TTL 的报告（默认）")
    refresh_p.add_argument("--all", dest="recompute_all", action="store_true", help="无视新鲜度，全部竞品重爬")

    timeline_p = sub.add_parser("timeline", help="查看竞品时间线事件（版本/功能/价格/榜单变化）")
    timeline_p.add_argument("competitor", nargs="?", default=None, help="竞品名称")

    schedule_p = sub.add_parser("schedule", help="定时调度轮：重爬过期竞品 + 结构化导出 + 异动告警（设计文档 28；--daemon 前台跑内置调度器，设计文档 67 §2.3.1）")
    schedule_p.add_argument("--competitors", default=None, help="目标竞品（逗号分隔）；缺省用跟踪竞品")
    schedule_p.add_argument("--daemon", action="store_true", help="前台运行内置调度器（interval/cron 由 schedule 配置决定）")

    sub.add_parser("weekly", help="跨竞品周报聚合：本周价格/版本/榜单变化 + 置信度对比表（设计文档 67 §2.3.2）")

    report_p = sub.add_parser("report", help="报告审批（--status/--approve/--reject）+ 可视化导出（--html/--visual，设计文档 67 §3）")
    report_p.add_argument("--status", metavar="NAME", help="查询报告审批状态")
    report_p.add_argument("--approve", metavar="NAME", help="审批通过报告（JSON status → approved）")
    report_p.add_argument("--reject", metavar="NAME", help="驳回报告（status → rejected）")
    report_p.add_argument("--html", metavar="NAME", help="导出单文件自包含 HTML")
    report_p.add_argument("--visual", metavar="NAME", help="导出雷达图（对比报告，需 matplotlib optional）")
    report_p.add_argument("--note", default="", help="审批备注（配合 --approve/--reject）")

    benchmark_p = sub.add_parser("benchmark", help="运行评测基准（--ablate 追加消融对比，设计文档 30；--llm real 真实质量评测，设计文档 37）")
    benchmark_p.add_argument("--ablate", action="store_true", help="追加 4 组消融变体（full/no-rag/no-memory/no-rag+no-memory）并落盘 <data_dir>/reports/ablation/")
    benchmark_p.add_argument("--llm", choices=["mock", "real"], default="mock", help="LLM 模式：mock=确定性评测（默认），real=真实 LLM（需配置 API Key）")
    benchmark_p.add_argument("--tag", default=None, help="按 tag 过滤用例子集（如 normal）控制成本")
    benchmark_p.add_argument("--cost-limit", type=float, default=None, dest="cost_limit", help="真实评测成本护栏上限（美元），缺省 real 模式 $1.0")
    benchmark_p.add_argument("--engine", choices=["react", "langgraph", "both"], default=None, help="编排引擎对照（设计文档 51）：both=双引擎顺序跑并落盘对比表")

    sub.add_parser("rag-warmup", help="预缓存向量嵌入模型并打印向量层状态（设计文档 52 M2；唯一触网路径，需显式执行）")

    trace_p = sub.add_parser("trace", help="查看链路追踪（设计文档 54）：list=最近 trace 列表；show <sid>=文本瀑布图")
    trace_p.add_argument("action", nargs="?", choices=["list", "show"], default="list")
    trace_p.add_argument("sid", nargs="?", default=None, help="trace_id（通常即 session_id）")
    return parser


def main(argv: list[str] | None = None) -> int:
    # 设计文档 74 §3.1/E2：启动强制应用用户级 env（忽略 shell 注入的 DEEPSEEK_API_KEY / OPENAI_BASE_URL）
    from competitor_agent.config.user_env import apply_user_level_environment

    apply_user_level_environment()
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(level=load_config().observability.log_level, log_dir=get_data_dir() / "logs")
    engine = getattr(args, "engine", None) or "react"
    if args.command == "benchmark":
        # benchmark 的引擎选择（含 both 对照）透传 evaluation.benchmark，不进 facade 构造
        engine = "react"
    if args.command == "rag-warmup":
        # 无需 LLM/API 构造，在 _make_api 之前短路（设计文档 52 §2.2）
        return _run_rag_warmup()
    if args.command == "trace":
        # 链路追踪查看纯本地读 JSONL，无需构造 API/LLM（截图展示用）
        return _run_trace(args.action or "list", args.sid)
    api = _make_api(engine=engine)
    llm = _build_llm(load_config())
    use_llm = True

    if args.resume_id:
        _run_resume(api, args.resume_id)
        return 0
    if args.oneshot:
        return _run_analyze(api, args.oneshot, llm=llm, use_llm=use_llm)

    if args.command == "analyze":
        if args.mode != "team":
            print(f"[提示] --mode 已废弃，统一走 Lead ReAct 编排（设计文档 49），忽略 --mode={args.mode}")
        task = " ".join(args.task)
        return _run_analyze(api, task, out_dir=args.out_dir, mode=args.mode, llm=llm, use_llm=use_llm)
    if args.command == "history":
        reports = api.get_history(args.competitor)
        if not reports:
            print("（无历史记录）")
            return 0
        for r in reports:
            print(f"- {r.competitor.name} | {r.terminal_state} | {r.created_at}")
        return 0
    if args.command == "refresh":
        _run_refresh(api, " --all" if args.recompute_all else "--stale")
        return 0
    if args.command == "timeline":
        _run_timeline(api, args.competitor or "")
        return 0
    if args.command == "schedule":
        if getattr(args, "daemon", False):
            return _run_schedule_daemon(api)
        _run_schedule(api, args.competitors or "")
        return 0
    if args.command == "weekly":
        _run_weekly(api, args.command)
        return 0
    if args.command == "report":
        parts = []
        for flag in ("--status", "--approve", "--reject", "--html", "--visual"):
            value = getattr(args, flag.lstrip("-"), None)
            if value:
                parts += [flag, value]
        if args.note:
            parts += ["--note", args.note]
        _run_report(api, " ".join(parts))
        return 0
    if args.command == "benchmark":
        parts = ["--ablate"] if args.ablate else []
        if args.llm != "mock":
            parts += ["--llm", args.llm]
        if args.tag:
            parts += ["--tag", args.tag]
        if args.cost_limit is not None:
            parts += ["--cost-limit", str(args.cost_limit)]
        if args.engine:
            parts += ["--engine", args.engine]
        _run_benchmark(" ".join(parts))
        return 0

    # 无子命令 → 交互 REPL
    _repl(api, llm=llm, use_llm=use_llm)
    return 0


if __name__ == "__main__":
    from competitor_agent.observability.langfuse_exporter import flush_langfuse

    _exit_code = main()
    flush_langfuse()  # 进程退出前尽力排空 Langfuse 异步上报队列（可选 exporter）
    raise SystemExit(_exit_code)
