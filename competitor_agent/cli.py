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

from competitor_agent.core.command_registry import command_dispatch
from competitor_agent.core.input_sanitizer import sanitize_task
from competitor_agent.core.task_parser import parse_task
from competitor_agent.domain_types.report import CompetitorReport
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.llm.client import LLMClient

PROMPT = "competitor> "


def _make_api() -> CompetitorAnalysisAPI:
    return CompetitorAnalysisAPI(llm=LLMClient(), use_llm=True)


def _print_report(report: CompetitorReport) -> None:
    print(report.markdown_report)
    if report.gaps_pending:
        print(f"\n[提示] {len(report.gaps_pending)} 个缺口未关闭，可用 /resume 继续。")


def _run_analyze(api: CompetitorAnalysisAPI, args: str, out_dir: str | None = None, mode: str = "team") -> None:
    """analyze 子命令 + /analyze 处理器"""
    args = sanitize_task(args.strip())
    if not args:
        print("用法: analyze <竞品或任务>")
        return
    parsed = parse_task(args, llm=LLMClient(), use_llm=True)
    if parsed.is_compare and len(parsed.competitors) >= 2:
        report = api.compare(parsed.competitors[0], parsed.competitors[1])
        markdown = report.markdown_report
        print(markdown)
        name = parsed.primary_competitor
    else:
        rep = api.analyze(args, mode=mode)
        _print_report(rep)
        markdown = rep.markdown_report
        name = parsed.primary_competitor
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


def _run_benchmark(_args: str) -> None:
    from competitor_agent.evaluation.benchmark import Benchmark

    report = Benchmark().run()
    print(f"n_cases={report.n_cases} field_acc={report.accuracy.field_accuracy:.4f} "
          f"halluc={report.accuracy.hallucination_rate:.4f} "
          f"tool_sel={report.strategy.tool_selection_accuracy:.4f} "
          f"cost_eff={report.strategy.cost_efficiency:.4f}")


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


def _repl(api: CompetitorAnalysisAPI) -> NoReturn:
    """交互 REPL：斜杠命令路由 + 自由文本任务"""
    print("competitor_agent 交互模式（输入 /help 查看命令，Ctrl+C / Ctrl+D 退出）")
    handlers = {
        "analyze": lambda a: _run_analyze(api, a),
        "compare": lambda a: _run_compare_repl(api, a),
        "history": lambda a: _run_history(api, a),
        "resume": lambda a: _run_resume(api, a),
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
        _run_analyze(api, line)


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

    sub.add_parser("benchmark", help="运行评测基准")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    api = _make_api()

    if args.resume_id:
        _run_resume(api, args.resume_id)
        return 0
    if args.oneshot:
        _run_analyze(api, args.oneshot)
        return 0

    if args.command == "analyze":
        task = " ".join(args.task)
        _run_analyze(api, task, out_dir=args.out_dir, mode=args.mode)
        return 0
    if args.command == "history":
        reports = api.get_history(args.competitor)
        if not reports:
            print("（无历史记录）")
            return 0
        for r in reports:
            print(f"- {r.competitor.name} | {r.terminal_state} | {r.created_at}")
        return 0
    if args.command == "benchmark":
        _run_benchmark("")
        return 0

    # 无子命令 → 交互 REPL
    _repl(api)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
