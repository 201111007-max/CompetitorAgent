"""设计文档 76：黄金断言评测——判定器可注入 / 指标聚合 / benchmark 接线。

KeywordGoldenJudge 纯本地确定性（断网可跑）；LLMGoldenJudge 经注入 fake LLM 验证
prompt 组装与 verdict 解析；GoldenEvaluator 聚合召回/陷阱通过率；Benchmark.run()
末尾 _run_golden() 接线 + mock 连跑确定性（doc 76 §4.2/§4.3）。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import yaml
from competitor_agent.evaluation.benchmark import Benchmark
from competitor_agent.evaluation.golden import (
    GOLDEN_DIR,
    GoldenAssertion,
    GoldenEvaluator,
    GoldenTaskCase,
    GoldenVerdict,
    KeywordGoldenJudge,
    LLMGoldenJudge,
    build_golden_judge,
    load_golden_tasks,
)

_MUST = GoldenAssertion(id="m1", claim="Cursor 提供免费档 hobby", type="must_have")
_TRAP = GoldenAssertion(id="t1", claim="Cursor 于 2025 年被 Anthropic 收购", type="trap")


class TestKeywordGoldenJudge:
    def test_must_have_covered(self) -> None:
        judge = KeywordGoldenJudge()
        assert judge.judge("Cursor 的免费档（hobby）有次数限制", _MUST) is GoldenVerdict.covered

    def test_must_have_missing(self) -> None:
        judge = KeywordGoldenJudge()
        assert judge.judge("完全无关的正文内容", _MUST) is GoldenVerdict.missing

    def test_must_have_low_ratio_missing(self) -> None:
        judge = KeywordGoldenJudge()
        # 多信息词命中不足 0.6 → missing
        claim = GoldenAssertion(id="m2", claim="alpha beta gamma delta epsilon", type="must_have")
        assert judge.judge("只提到 alpha 和 beta 的报告", claim) is GoldenVerdict.missing

    def test_trap_passed_when_absent(self) -> None:
        judge = KeywordGoldenJudge()
        assert judge.judge("正常的 Cursor 功能介绍正文", _TRAP) is GoldenVerdict.passed

    def test_trap_tripped_when_repeated(self) -> None:
        judge = KeywordGoldenJudge()
        assert judge.judge("2025 年传闻 Cursor 被 Anthropic 收购", _TRAP) is GoldenVerdict.tripped

    def test_trap_single_hit_not_tripped(self) -> None:
        """报告合理提到 Anthropic（单一信息词）不应误判 trap 失败。"""
        judge = KeywordGoldenJudge()
        assert judge.judge("与 Anthropic 的 Claude 系列不同，Cursor 是编辑器", _TRAP) is GoldenVerdict.passed

    def test_product_tokens_ignored(self) -> None:
        """产品名（cursor 等）对判定零信息量：报告必然提到产品名。"""
        tokens = KeywordGoldenJudge()._ignore
        assert "cursor" in tokens

    def test_never_contradicted(self) -> None:
        judge = KeywordGoldenJudge()
        assert judge.judge("矛盾内容", _MUST) is not GoldenVerdict.contradicted

    def test_empty_claim_conservative(self) -> None:
        judge = KeywordGoldenJudge()
        empty = GoldenAssertion(id="e", claim="的 了 和", type="trap")
        assert judge.judge("任何文本", empty) is GoldenVerdict.passed


class _FakeLLM:
    def __init__(self, reply: str = '{"verdict": "covered"}', error: bool = False) -> None:
        self._reply = reply
        self._error = error
        self.last_messages: list[dict[str, str]] = []

    def complete(self, messages: list[dict[str, str]], json_mode: bool = False) -> str:
        if self._error:
            raise RuntimeError("llm down")
        self.last_messages = messages
        return self._reply


class TestLLMGoldenJudge:
    def test_parses_verdict(self) -> None:
        llm = _FakeLLM('{"verdict": "contradicted"}')
        judge = LLMGoldenJudge(llm)
        assert judge.judge("报告", _MUST) is GoldenVerdict.contradicted

    def test_prompt_contains_claim_and_report(self) -> None:
        llm = _FakeLLM()
        judge = LLMGoldenJudge(llm)
        judge.judge("这是报告正文", _MUST)
        content = llm.last_messages[0]["content"]
        assert _MUST.claim in content
        assert "这是报告正文" in content

    def test_garbage_json_falls_back(self) -> None:
        judge = LLMGoldenJudge(_FakeLLM("不是 JSON"))
        assert judge.judge("报告", _MUST) is GoldenVerdict.missing
        assert judge.judge("报告", _TRAP) is GoldenVerdict.passed

    def test_llm_error_falls_back(self) -> None:
        judge = LLMGoldenJudge(_FakeLLM(error=True))
        assert judge.judge("报告", _MUST) is GoldenVerdict.missing

    def test_unknown_verdict_falls_back(self) -> None:
        judge = LLMGoldenJudge(_FakeLLM('{"verdict": "不知道"}'))
        assert judge.judge("报告", _MUST) is GoldenVerdict.missing


class TestBuildGoldenJudge:
    def test_mock_builds_keyword(self) -> None:
        assert isinstance(build_golden_judge("mock", None), KeywordGoldenJudge)

    def test_real_builds_llm(self) -> None:
        llm = _FakeLLM()
        assert isinstance(build_golden_judge("real", llm), LLMGoldenJudge)

    def test_real_without_llm_builds_keyword(self) -> None:
        assert isinstance(build_golden_judge("real", None), KeywordGoldenJudge)


def _write_task(path: Path, task_id: str, verified: str, n: int = 2) -> None:
    data = {
        "task": f"任务 {task_id}",
        "task_id": task_id,
        "verified_date": verified,
        "assertions": [
            {"id": f"{task_id}-{i}", "claim": f"断言 {i} 内容", "type": "must_have", "tags": ["x"]}
            for i in range(n)
        ],
    }
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


class TestLoadGoldenTasks:
    def test_loads_and_stale_note_empty_verified(self, tmp_path: Path) -> None:
        _write_task(tmp_path / "a.yaml", "t1", "")
        tasks = load_golden_tasks(tmp_path, today=date(2026, 9, 9))
        assert len(tasks) == 1
        assert tasks[0].task_id == "t1"
        assert tasks[0].assertions[0].id == "t1-0"
        assert "待核实" in tasks[0].stale_note

    def test_stale_note_old_verified_date(self, tmp_path: Path) -> None:
        _write_task(tmp_path / "a.yaml", "t1", "2026-01-01")
        tasks = load_golden_tasks(tmp_path, today=date(2026, 9, 9))
        assert "90 天" in tasks[0].stale_note

    def test_fresh_verified_date_no_note(self, tmp_path: Path) -> None:
        _write_task(tmp_path / "a.yaml", "t1", "2026-09-01")
        tasks = load_golden_tasks(tmp_path, today=date(2026, 9, 9))
        assert tasks[0].stale_note == ""

    def test_bad_yaml_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "bad.yaml").write_text("::: not yaml [[", encoding="utf-8")
        (tmp_path / "non_dict.yaml").write_text("- a\n- b\n", encoding="utf-8")
        assert load_golden_tasks(tmp_path) == []

    def test_missing_dir_empty(self, tmp_path: Path) -> None:
        assert load_golden_tasks(tmp_path / "nope") == []

    def test_default_golden_dir_has_three_tasks(self) -> None:
        """仓库根 evals/golden 三个任务集已落盘（verified_date 待用户核实）。"""
        tasks = load_golden_tasks(GOLDEN_DIR)
        assert {t.task_id for t in tasks} >= {"analyze_cursor", "compare_claude_code_vs_copilot", "track_codex_changes"}
        for task in tasks:
            assert len(task.assertions) >= 30
            assert task.task


class TestGoldenTaskCase:
    def test_single_competitor_inferred(self) -> None:
        case = GoldenTaskCase("分析 Cursor")
        assert case.competitor == "cursor"

    def test_compare_task_no_single_competitor(self) -> None:
        case = GoldenTaskCase("对比 Claude Code 和 Copilot")
        assert case.competitor == ""


class _FakeAPI:
    def __init__(self, text: str) -> None:
        self._text = text

    def run(self, task: str, **kwargs: object) -> object:
        return SimpleNamespace(markdown_report=self._text)


class TestGoldenEvaluator:
    def test_recall_and_trap_rates(self) -> None:
        text = "Cursor 提供免费档 hobby；2025 年传闻被 Anthropic 收购。"
        tasks = [
            SimpleNamespace(
                task_id="t1",
                task="任务",
                stale_note="",
                assertions=[
                    _MUST,
                    GoldenAssertion(id="m2", claim="Cursor 支持 tab 补全", type="must_have"),
                    _TRAP,
                ],
            )
        ]
        result = GoldenEvaluator(KeywordGoldenJudge(), lambda case: _FakeAPI(text), tasks).run()
        assert result.has_data
        assert result.n_must_have == 2
        assert result.n_trap == 1
        assert result.must_have_recall == 0.5  # m1 covered、m2 missing
        assert result.trap_pass_rate == 0.0  # trap 复述 → tripped
        assert result.per_task["t1"]["must_have_recall"] == 0.5

    def test_task_failure_conservative(self) -> None:
        """单任务 api.run 崩溃不影响其余任务（其余任务照常判定）。"""
        tasks = [
            SimpleNamespace(task_id="bad", task="坏任务", stale_note="", assertions=[_MUST]),
            SimpleNamespace(task_id="good", task="好任务", stale_note="", assertions=[_MUST]),
        ]

        def build_api(case: object) -> object:
            if case.task == "坏任务":
                raise RuntimeError("boom")
            return _FakeAPI("Cursor 提供免费档 hobby")

        result = GoldenEvaluator(KeywordGoldenJudge(), build_api, tasks).run()
        assert result.per_task["bad"]["must_have_recall"] == 0.0
        assert result.per_task["good"]["must_have_recall"] == 1.0

    def test_stale_warnings_collected(self) -> None:
        tasks = [SimpleNamespace(task_id="t1", task="任务", stale_note="t1: 待核实", assertions=[_MUST])]
        result = GoldenEvaluator(KeywordGoldenJudge(), lambda case: _FakeAPI(""), tasks).run()
        assert result.stale_warnings == ["t1: 待核实"]


class TestBenchmarkGoldenWiring:
    def _golden_dir(self, tmp_path: Path) -> Path:
        gdir = tmp_path / "golden"
        gdir.mkdir()
        data = {
            "task": "分析 Cursor",
            "task_id": "g1",
            "verified_date": "",
            "assertions": [
                {"id": "a1", "claim": "Cursor 支持 tab 补全与 agent 模式", "type": "must_have"},
                {"id": "a2", "claim": "Cursor 于 2025 年被 Anthropic 收购", "type": "trap"},
            ],
        }
        (gdir / "g1.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        return gdir

    def test_run_attaches_golden_result(self, tmp_path: Path) -> None:
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        report = Benchmark(
            llm_mode="mock",
            fixtures_dir=fixtures,
            golden_dir=self._golden_dir(tmp_path),
            use_golden_cache=False,
        ).run()
        assert report.golden.has_data
        assert report.golden.n_must_have == 1
        assert report.golden.n_trap == 1
        assert report.to_dict()["golden"]["n_tasks"] == 1
        # mock 报告不含 trap 内容 → trap passed
        assert report.golden.trap_pass_rate == 1.0

    def test_mock_determinism_three_runs(self, tmp_path: Path) -> None:
        """doc 76 §4.2：mock 模式连跑 3 次 golden 指标逐位一致。"""
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        gdir = self._golden_dir(tmp_path)

        def one_run() -> tuple[float, float]:
            return Benchmark(
                llm_mode="mock", fixtures_dir=fixtures, golden_dir=gdir, use_golden_cache=False
            ).run().golden.must_have_recall, Benchmark(
                llm_mode="mock", fixtures_dir=fixtures, golden_dir=gdir, use_golden_cache=False
            ).run().golden.trap_pass_rate

        runs = [one_run() for _ in range(3)]
        assert len(set(runs)) == 1

    def test_cache_reuses_result(self, tmp_path: Path) -> None:
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        gdir = self._golden_dir(tmp_path)
        b1 = Benchmark(llm_mode="mock", fixtures_dir=fixtures, golden_dir=gdir).run()
        b2 = Benchmark(llm_mode="mock", fixtures_dir=fixtures, golden_dir=gdir).run()
        assert b1.golden is b2.golden  # 命中进程级缓存（同一对象）

    def test_missing_golden_dir_no_data(self, tmp_path: Path) -> None:
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        report = Benchmark(llm_mode="mock", fixtures_dir=fixtures, golden_dir=tmp_path / "nope").run()
        assert not report.golden.has_data
        assert report.golden.must_have_recall == 0.0
