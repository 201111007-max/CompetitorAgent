"""设计文档 76 §2.4：评测指标版本化——快照 / 追加 / diff（纯函数可计算）。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from competitor_agent.evaluation.history import (
    DEFAULT_HISTORY_PATH,
    append_history,
    diff,
    git_head,
    load_history,
    snapshot,
)


def _fake_report(cost_by_case: dict[str, float] | None = None) -> SimpleNamespace:
    case_cost = cost_by_case or {"c1": 0.5, "c2": 1.5}
    return SimpleNamespace(
        accuracy=SimpleNamespace(field_accuracy=0.95, hallucination_rate=0.02, f1=0.93),
        strategy=SimpleNamespace(tool_selection_accuracy=0.9, cost_efficiency=0.8),
        trace_completeness=1.0,
        golden=SimpleNamespace(must_have_recall=0.7, trap_pass_rate=0.9, contradicted_count=1),
        llm_mode="mock",
        cost_usd=2.0,
        per_case_cost=case_cost,
        harness_version="0.12.0",
        n_cases=29,
    )


class TestGitHead:
    def test_returns_short_hash(self) -> None:
        head = git_head()
        assert head
        assert head == "unknown" or (len(head) >= 7 and all(c in "0123456789abcdef" for c in head))


class TestSnapshot:
    def test_metrics_numeric_only_and_placeholders(self) -> None:
        snap = snapshot(_fake_report(), commit="abc1234", wall_seconds=1.2345)
        metrics = snap["metrics"]
        assert metrics["field_accuracy"] == 0.95
        assert metrics["must_have_recall"] == 0.7
        assert metrics["trap_pass_rate"] == 0.9
        assert metrics["judge_spearman"] is None  # doc 83 校准后回填
        assert metrics["wall_seconds"] == 1.234
        assert snap["commit"] == "abc1234"
        assert snap["harness_version"] == "0.12.0"
        assert snap["llm_mode"] == "mock"
        assert snap["ts"]

    def test_per_case_cost_averaged(self) -> None:
        snap = snapshot(_fake_report())
        assert snap["metrics"]["per_case_cost"] == 1.0

    def test_default_commit_is_git_head(self) -> None:
        snap = snapshot(_fake_report())
        assert snap["commit"] == git_head()


class TestAppendLoad:
    def test_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "evals" / "history.jsonl"
        append_history(path, snapshot(_fake_report(), commit="aaaaaaa"))
        append_history(path, snapshot(_fake_report(), commit="bbbbbbb"))
        snaps = load_history(path)
        assert [s["commit"] for s in snaps] == ["aaaaaaa", "bbbbbbb"]

    def test_bad_lines_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "history.jsonl"
        snap = json.dumps(snapshot(_fake_report(), commit="ccccccc"), ensure_ascii=False)
        path.write_text(f"{snap}\nnot-json\n\n", encoding="utf-8")
        assert len(load_history(path)) == 1

    def test_missing_file_empty(self, tmp_path: Path) -> None:
        assert load_history(tmp_path / "nope.jsonl") == []


class TestDiff:
    def _history(self, tmp_path: Path) -> Path:
        path = tmp_path / "history.jsonl"
        append_history(path, snapshot(_fake_report({"c1": 1.0}), commit="aaaaaaa"))
        snap = snapshot(_fake_report({"c1": 0.5}), commit="bbbbbbb")
        snap["metrics"]["field_accuracy"] = 0.97
        snap["metrics"]["hallucination_rate"] = 0.01
        append_history(path, snap)
        return path

    def test_diff_by_commit_prefix(self, tmp_path: Path) -> None:
        table = diff("aaaaaaa", "bbbbbbb", self._history(tmp_path))
        assert "aaaaaaa" in table
        assert "bbbbbbb" in table
        assert "field_accuracy" in table
        assert "+0.0200" in table  # 0.95 → 0.97

    def test_diff_latest_n(self, tmp_path: Path) -> None:
        path = self._history(tmp_path)
        table = diff("latest/2", "latest", path)
        assert "aaaaaaa" in table and "bbbbbbb" in table

    def test_diff_none_metric_placeholder(self, tmp_path: Path) -> None:
        table = diff("aaaaaaa", "bbbbbbb", self._history(tmp_path))
        assert "judge_spearman" in table
        assert "—" in table

    def test_unknown_rev_error(self, tmp_path: Path) -> None:
        try:
            diff("deadbee", "latest", self._history(tmp_path))
        except ValueError as exc:
            assert "未找到快照" in str(exc)
        else:
            raise AssertionError("应抛 ValueError")

    def test_latest_out_of_range(self, tmp_path: Path) -> None:
        try:
            diff("latest", "latest/9", self._history(tmp_path))
        except ValueError as exc:
            assert "越界" in str(exc)
        else:
            raise AssertionError("应抛 ValueError")

    def test_empty_history_message(self, tmp_path: Path) -> None:
        assert "无快照" in diff("latest", "latest", tmp_path / "nope.jsonl")


class TestDefaultPath:
    def test_points_to_repo_evals(self) -> None:
        assert DEFAULT_HISTORY_PATH.name == "history.jsonl"
        assert DEFAULT_HISTORY_PATH.parent.name == "evals"
