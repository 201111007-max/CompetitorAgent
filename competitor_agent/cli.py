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

from competitor_agent.config.loader import load_config
from competitor_agent.core.command_registry import command_dispatch
from competitor_agent.core.input_sanitizer import sanitize_task
from competitor_agent.core.task_parser import ResolutionDecision, parse_task
from competitor_agent.domain_types.report import CompetitorReport
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.llm.client import LLMClient
from competitor_agent.observability.logger import setup_logging
from competitor_agent.secret_vault import get_data_dir

PROMPT = "competitor> "


def _make_api() -> CompetitorAnalysisAPI:
    return CompetitorAnalysisAPI(llm=LLMClient(model=load_config().model, base_url=load_config().api_base_url), use_llm=True, config=load_config())


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
    use_llm: bool = False,
) -> None:
    """analyze 子命令 + /analyze 处理器"""
    args = sanitize_task(args.strip())
    if not args:
        print("用法: analyze <竞品或任务>")
        return
    parsed = parse_task(args, llm=llm, use_llm=use_llm)
    markdown = ""
    name = parsed.primary_competitor
    if parsed.resolution == ResolutionDecision.DISCOVERY:
        # 市场普查/发现：联网发现竞品 → 逐个分析 → 品类格局报告
        report = api.discover(args)
        markdown = report.markdown_report
        print(markdown)
    elif parsed.is_compare and len(parsed.competitors) >= 2:
        report = api.compare(*parsed.competitors)
        markdown = report.markdown_report
        print(markdown)
        name = "compare"
    else:
        rep = api.analyze(args, mode=mode)
        _print_report(rep)
        markdown = rep.markdown_report
    if out_dir:
        _save_markdown(markdown, name, out_dir)


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
    from pathlib import Path

    from competitor_agent.evaluation.benchmark import Benchmark

    ablate = "--ablate" in args.split()
    report = Benchmark().run()
    print(f"n_cases={report.n_cases} field_acc={report.accuracy.field_accuracy:.4f} "
          f"halluc={report.accuracy.hallucination_rate:.4f} "
          f"tool_sel={report.strategy.tool_selection_accuracy:.4f} "
          f"cost_eff={report.strategy.cost_efficiency:.4f}")
    if ablate:
        # 设计文档 30：消融/对比实验——5 组变体全跑 + 落盘 reports/ablation/
        from competitor_agent.evaluation.ablation import (
            AblationRunner,
            render_ablation_table,
            write_ablation_report,
        )

        results = AblationRunner().run()
        paths = write_ablation_report(results, Path("reports/ablation"))
        print(render_ablation_table(results))
        for p in paths:
            print(f"ablation: {p}")


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


def _repl(api: CompetitorAnalysisAPI, llm: LLMClient | None = None, use_llm: bool = False) -> NoReturn:
    """交互 REPL：斜杠命令路由 + 自由文本任务"""
    print("competitor_agent 交互模式（输入 /help 查看命令，Ctrl+C / Ctrl+D 退出）")
    handlers = {
        "analyze": lambda a: _run_analyze(api, a, llm=llm, use_llm=use_llm),
        "compare": lambda a: _run_compare_repl(api, a),
        "history": lambda a: _run_history(api, a),
        "resume": lambda a: _run_resume(api, a),
        "refresh": lambda a: _run_refresh(api, a),
        "timeline": lambda a: _run_timeline(api, a),
        "schedule": lambda a: _run_schedule(api, a),
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
    report = api.compare(parts[0], parts[1])
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
    analyze_p.add_argument("--mode", default="team", choices=["single", "team"], help="执行模式: team=多 Agent 流水线(默认), single=单 Agent")

    history_p = sub.add_parser("history", help="查询历史分析记录")
    history_p.add_argument("--competitor", default=None, help="按竞品过滤")

    refresh_p = sub.add_parser("refresh", help="陈旧度检测/定时重爬过期竞品报告（设计文档 26）")
    refresh_p.add_argument("--stale", action="store_true", help="仅刷新超过维度 TTL 的报告（默认）")
    refresh_p.add_argument("--all", dest="recompute_all", action="store_true", help="无视新鲜度，全部竞品重爬")

    timeline_p = sub.add_parser("timeline", help="查看竞品时间线事件（版本/功能/价格/榜单变化）")
    timeline_p.add_argument("competitor", nargs="?", default=None, help="竞品名称")

    schedule_p = sub.add_parser("schedule", help="定时调度轮：重爬过期竞品 + 结构化导出 + 异动告警（设计文档 28）")
    schedule_p.add_argument("--competitors", default=None, help="目标竞品（逗号分隔）；缺省用跟踪竞品")

    benchmark_p = sub.add_parser("benchmark", help="运行评测基准（--ablate 追加消融对比，设计文档 30）")
    benchmark_p.add_argument("--ablate", action="store_true", help="追加 5 组消融变体（full/no-rag/no-memory/no-rag+no-memory/no-llm-rule）并落盘 reports/ablation/")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(level=load_config().observability.log_level, log_dir=get_data_dir() / "logs")
    api = _make_api()
    llm = LLMClient(model=load_config().model, base_url=load_config().api_base_url)
    use_llm = True

    if args.resume_id:
        _run_resume(api, args.resume_id)
        return 0
    if args.oneshot:
        _run_analyze(api, args.oneshot, llm=llm, use_llm=use_llm)
        return 0

    if args.command == "analyze":
        task = " ".join(args.task)
        _run_analyze(api, task, out_dir=args.out_dir, mode=args.mode, llm=llm, use_llm=use_llm)
        return 0
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
        _run_schedule(api, args.competitors or "")
        return 0
    if args.command == "benchmark":
        _run_benchmark(" --ablate" if args.ablate else "")
        return 0

    # 无子命令 → 交互 REPL
    _repl(api, llm=llm, use_llm=use_llm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
