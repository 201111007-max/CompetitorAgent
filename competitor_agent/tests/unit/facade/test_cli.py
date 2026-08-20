"""cli.py 单测（M5.1）：解析器 + 子命令 + handlers

设计文档 47：仅 LLM 解析/规划/分析；无 Key → 打印提示 + 退出码 2。
analyze 路由用 mock LLM（BenchmarkMockLLM 从任务文本确定性推断竞品/分辨率）。
"""

from competitor_agent.cli import (
    _repl,
    _run_analyze,
    _run_benchmark,
    _run_compare_repl,
    _run_help,
    _run_history,
    _run_resume,
    build_parser,
)
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.report import ComparisonReport
from competitor_agent.evaluation.benchmark import BenchmarkMockLLM
from competitor_agent.llm.client import LLMClient


def _mock_llm() -> LLMClient:
    """确定性 mock LLM：从任务文本推断竞品/分辨率（无 Key 可测 analyze 路由）。"""
    return LLMClient(call_func=BenchmarkMockLLM().complete)


class StubReport:
    def __init__(self, name: str = "cursor") -> None:
        self.competitor = Competitor(name=name)
        self.dimension_results = []
        self.overall_confidence = 0.5
        self.gaps_pending = []
        self.markdown_report = f"# {name} 竞品分析报告"
        self.terminal_state = "success"
        self.created_at = "2026-01-01T00:00:00+00:00"


class StubAPI:
    def analyze(self, task, conversation_history=None, mode="single"):
        return StubReport()

    def compare(self, a, b=None):
        return ComparisonReport(
            competitors=[Competitor(name=a), Competitor(name=b or "b")],
            reports=[StubReport(a), StubReport(b or "b")],
            markdown_report=f"# {a} vs {b or 'b'} 对比报告",
        )

    def discover(self, task):
        return ComparisonReport(
            competitors=[Competitor(name="cursor"), Competitor(name="windsurf")],
            reports=[StubReport("cursor"), StubReport("windsurf")],
            markdown_report="# cursor vs windsurf 竞品格局对比报告\n\n## 品类格局矩阵",
        )

    def get_history(self, competitor=None):
        return [StubReport(competitor or "cursor")]

    def continue_analysis(self, session_id):
        return StubReport()


class TestBuildParser:
    def test_analyze_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["analyze", "Cursor", "--out", "reports/"])
        assert args.command == "analyze"
        assert args.out_dir == "reports/"
        assert args.task == ["Cursor"]

    def test_history_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["history", "--competitor", "cursor"])
        assert args.command == "history"
        assert args.competitor == "cursor"

    def test_benchmark_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["benchmark"])
        assert args.command == "benchmark"

    def test_schedule_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["schedule", "--competitors", "cursor,copilot"])
        assert args.command == "schedule"
        assert args.competitors == "cursor,copilot"

    def test_schedule_subcommand_default(self):
        parser = build_parser()
        args = parser.parse_args(["schedule"])
        assert args.command == "schedule"
        assert args.competitors is None

    def test_oneshot_flag(self):
        parser = build_parser()
        args = parser.parse_args(["-z", "分析 Cursor"])
        assert args.oneshot == "分析 Cursor"

    def test_continue_flag(self):
        parser = build_parser()
        args = parser.parse_args(["-c", "sess_abc"])
        assert args.resume_id == "sess_abc"


class TestGeneralHandlers:
    def test_run_help_lists_commands(self, capsys):
        _run_help("")
        captured = capsys.readouterr()
        assert "/analyze" in captured.out
        assert "/compare" in captured.out
        assert "/history" in captured.out
        assert "/resume" in captured.out
        assert "/benchmark" in captured.out
        assert "/help" in captured.out

    def test_run_help_specific_command(self, capsys):
        _run_help("compare")
        captured = capsys.readouterr()
        assert "/compare" in captured.out

    def test_run_help_unknown(self, capsys):
        _run_help("wat")
        captured = capsys.readouterr()
        assert "未知命令" in captured.out

    def test_run_benchmark_output(self, capsys):
        _run_benchmark("")
        captured = capsys.readouterr()
        assert "n_cases=" in captured.out


class TestRunAnalyze:
    def test_analyze_single_prints_report(self, capsys):
        _run_analyze(StubAPI(), "Cursor", llm=_mock_llm())
        captured = capsys.readouterr()
        assert "竞品分析报告" in captured.out

    def test_analyze_compare_task(self, capsys):
        _run_analyze(StubAPI(), "对比 Cursor 和 Windsurf", llm=_mock_llm())
        captured = capsys.readouterr()
        assert "对比报告" in captured.out

    def test_analyze_empty_args_shows_usage(self, capsys):
        _run_analyze(StubAPI(), "")
        captured = capsys.readouterr()
        assert "用法" in captured.out

    def test_analyze_writes_out_file(self, tmp_path, capsys):
        _run_analyze(StubAPI(), "Cursor", out_dir=str(tmp_path), llm=_mock_llm())
        files = list(tmp_path.glob("*.md"))
        assert files
        assert "竞品分析报告" in files[0].read_text(encoding="utf-8")

    def test_analyze_discovery_task(self, capsys):
        """设计文档 20：普查任务路由到 discover，输出品类格局矩阵"""
        _run_analyze(StubAPI(), "帮我寻找市场上所有 AI coding agent", llm=_mock_llm())
        captured = capsys.readouterr()
        assert "竞品格局对比报告" in captured.out
        assert "品类格局矩阵" in captured.out

    def test_analyze_no_key_prints_error_exit_2(self, capsys):
        """设计文档 47：无 LLM → 打印需要配置 API Key，退出码 2。"""
        code = _run_analyze(StubAPI(), "Cursor", llm=None)
        captured = capsys.readouterr()
        assert code == 2
        assert "需要配置 LLM API Key" in captured.out


class TestRunHistory:
    def test_history_lists(self, capsys):
        _run_history(StubAPI(), "--competitor cursor")
        captured = capsys.readouterr()
        assert "cursor" in captured.out

    def test_history_empty(self, capsys):
        class NoHistoryAPI(StubAPI):
            def get_history(self, competitor=None):
                return []

        _run_history(NoHistoryAPI(), "")
        captured = capsys.readouterr()
        assert "无历史记录" in captured.out


class TestRunResume:
    def test_resume_with_session(self, capsys):
        _run_resume(StubAPI(), "sess_abc")
        captured = capsys.readouterr()
        assert "竞品分析报告" in captured.out

    def test_resume_no_checkpoints(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "competitor_agent.core.checkpoint.list_checkpoints", list
        )
        _run_resume(StubAPI(), "")
        captured = capsys.readouterr()
        assert "无可用 checkpoint" in captured.out


class TestMain:
    def _patch_api(self, monkeypatch, api=None):
        monkeypatch.setattr("competitor_agent.cli._make_api", lambda engine="react": api or StubAPI())
        # main() 以 kwargs 构造 LLMClient；mock 需接受任意参数并返回确定性 LLM
        monkeypatch.setattr(
            "competitor_agent.cli.LLMClient", lambda *a, **kw: _mock_llm()
        )

    def test_main_oneshot(self, monkeypatch, capsys):
        self._patch_api(monkeypatch)
        from competitor_agent.cli import main

        assert main(["-z", "Cursor"]) == 0
        captured = capsys.readouterr()
        assert "竞品分析报告" in captured.out

    def test_main_continue(self, monkeypatch, capsys):
        self._patch_api(monkeypatch)
        from competitor_agent.cli import main

        assert main(["-c", "sess_abc"]) == 0
        captured = capsys.readouterr()
        assert "竞品分析报告" in captured.out

    def test_main_analyze_subcommand(self, monkeypatch, capsys):
        self._patch_api(monkeypatch)
        from competitor_agent.cli import main

        assert main(["analyze", "Cursor"]) == 0
        captured = capsys.readouterr()
        assert "竞品分析报告" in captured.out

    def test_main_history_subcommand(self, monkeypatch, capsys):
        self._patch_api(monkeypatch)
        from competitor_agent.cli import main

        assert main(["history", "--competitor", "cursor"]) == 0
        captured = capsys.readouterr()
        assert "cursor" in captured.out

    def test_main_benchmark_subcommand(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "competitor_agent.cli._run_benchmark", lambda a: None
        )
        from competitor_agent.cli import main

        assert main(["benchmark"]) == 0

    def test_main_benchmark_ablate_subcommand(self, monkeypatch, capsys):
        """--ablate 应透传给 _run_benchmark（触发消融对比，设计文档 30）。"""
        calls = []
        monkeypatch.setattr("competitor_agent.cli._run_benchmark", lambda a: calls.append(a))
        from competitor_agent.cli import main

        assert main(["benchmark", "--ablate"]) == 0
        assert calls == ["--ablate"]

    def test_main_benchmark_llm_real_passthrough(self, monkeypatch):
        """--llm real/--tag/--cost-limit 应透传给 _run_benchmark（设计文档 37）。"""
        calls = []
        monkeypatch.setattr("competitor_agent.cli._run_benchmark", lambda a: calls.append(a))
        from competitor_agent.cli import main

        assert main(["benchmark", "--llm", "real", "--tag", "normal", "--cost-limit", "0.5"]) == 0
        assert calls == ["--llm real --tag normal --cost-limit 0.5"]


class TestCompareRepl:
    def test_compare_two(self, capsys):
        _run_compare_repl(StubAPI(), "Cursor Windsurf")
        captured = capsys.readouterr()
        assert "对比报告" in captured.out

    def test_compare_with_he(self, capsys):
        _run_compare_repl(StubAPI(), "Cursor 和 Windsurf")
        captured = capsys.readouterr()
        assert "对比报告" in captured.out

    def test_compare_insufficient_args(self, capsys):
        _run_compare_repl(StubAPI(), "Cursor")
        captured = capsys.readouterr()
        assert "用法" in captured.out

    def test_compare_empty(self, capsys):
        _run_compare_repl(StubAPI(), "")
        captured = capsys.readouterr()
        assert "用法" in captured.out


class TestRepl:
    def test_repl_exits_on_eof(self, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(EOFError()))
        try:
            _repl(StubAPI())
        except SystemExit as exc:
            assert exc.code == 0
        captured = capsys.readouterr()
        assert "交互模式" in captured.out

    def test_repl_exit_command(self, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", lambda prompt="": "exit")
        try:
            _repl(StubAPI())
        except SystemExit as exc:
            assert exc.code == 0

    def test_repl_handles_plain_text(self, monkeypatch, capsys):
        inputs = iter(["Cursor", "exit"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
        try:
            _repl(StubAPI(), llm=_mock_llm())
        except SystemExit:
            pass
        captured = capsys.readouterr()
        assert "竞品分析报告" in captured.out