"""设计文档 83 §4.4：eval-anchor 人工锚点打分工具（工单 12/3）——TDD 先行。

纯函数层（competitor_agent/evaluation/anchor.py）：
- 报告池收集：排除已打分、盲评脱敏、确定性洗牌、重测混入
- 条目校验：理由必填、分数 1~5
- jsonl 追加与统计：分布、重测一致率、分差>1 作废标记
"""

import json
from pathlib import Path

from competitor_agent.evaluation.anchor import (
    AnchorItem,
    anchor_stats,
    append_anchor,
    collect_pool,
    load_scored_hashes,
    report_hash,
    validate_entry,
)


def _make_report(tmp_path: Path, name: str, body: str = "# 报告\n正文") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


class TestReportHash:
    def test_stable_and_content_sensitive(self, tmp_path: Path) -> None:
        a1 = _make_report(tmp_path, "a.md", "内容一")
        a2 = _make_report(tmp_path, "b.md", "内容一")
        b = _make_report(tmp_path, "c.md", "内容二")
        assert report_hash(a1) == report_hash(a2)  # 同内容同 hash（盲评靠它关联重测）
        assert report_hash(a1) != report_hash(b)
        assert len(report_hash(a1)) == 12  # 短 hash，作展示名


class TestCollectPool:
    def _pool(self, tmp_path: Path) -> list[Path]:
        # 三份内容各异的报告（report_hash 按内容计算，内容相同会塌缩成同一 hash）
        return [
            _make_report(tmp_path, "r1.md", "报告一"),
            _make_report(tmp_path, "r2.md", "报告二"),
            _make_report(tmp_path, "r3.md", "报告三"),
        ]

    def test_excludes_scored_and_blinds(self, tmp_path: Path) -> None:
        pool = self._pool(tmp_path)
        scored = {report_hash(pool[0])}
        items = collect_pool(pool, scored_hashes=scored, retest_rate=0.0, seed=42)
        hashes = {it.hash for it in items}
        assert report_hash(pool[0]) not in hashes  # 已打分排除
        assert len(items) == 2
        for it in items:  # 盲评：展示名 = hash，不带文件名信息
            assert it.display == it.hash
            assert "r" not in it.display

    def test_deterministic_shuffle(self, tmp_path: Path) -> None:
        pool = self._pool(tmp_path)
        run1 = collect_pool(pool, set(), retest_rate=0.0, seed=7)
        run2 = collect_pool(pool, set(), retest_rate=0.0, seed=7)
        assert [it.hash for it in run1] == [it.hash for it in run2]

    def test_retest_mixed_in_blinded(self, tmp_path: Path) -> None:
        """已打分报告按 retest_rate 抽回（is_retest=True），仍盲态混入。"""
        pool = self._pool(tmp_path)
        first = pool[0]
        scored = {report_hash(first)}
        items = collect_pool(pool, scored_hashes=scored, retest_rate=1.0, seed=1)
        retests = [it for it in items if it.is_retest]
        assert len(retests) == 1
        assert retests[0].hash == report_hash(first)
        assert retests[0].display == report_hash(first)  # 盲态：不打分者看不出是重测


class TestValidateEntry:
    def test_reason_required(self) -> None:
        assert validate_entry(4, "") is not None  # 空理由 → 错误信息
        assert validate_entry(4, "  ") is not None  # 纯空白同罪
        assert validate_entry(4, "跨维度推断有证据") is None

    def test_score_range(self) -> None:
        for bad in (0, 6, -1):
            assert validate_entry(bad, "理由") is not None
        for good in (1, 2, 3, 4, 5):
            assert validate_entry(good, "理由") is None


class TestAppendAndStats:
    def test_append_load_roundtrip(self, tmp_path: Path) -> None:
        out = tmp_path / "anchors.jsonl"
        append_anchor(out, {"report_hash": "h1", "score": 4, "reason": "有跨维度推断", "is_retest": False})
        append_anchor(out, {"report_hash": "h1", "score": 4, "reason": "重测仍认为成立", "is_retest": True})
        append_anchor(out, {"report_hash": "h2", "score": 2, "reason": "纯罗列", "is_retest": False})
        lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
        assert len(lines) == 3
        assert lines[0]["report_hash"] == "h1"

    def test_stats_distribution_and_retest_consistency(self, tmp_path: Path) -> None:
        out = tmp_path / "anchors.jsonl"
        append_anchor(out, {"report_hash": "h1", "score": 4, "reason": "r1", "is_retest": False})
        append_anchor(out, {"report_hash": "h1", "score": 4, "reason": "r1-retest", "is_retest": True})
        append_anchor(out, {"report_hash": "h2", "score": 5, "reason": "r2", "is_retest": False})
        append_anchor(out, {"report_hash": "h2", "score": 3, "reason": "r2-retest", "is_retest": True})
        append_anchor(out, {"report_hash": "h3", "score": 2, "reason": "r3", "is_retest": False})
        stats = anchor_stats(out)
        assert stats["n"] == 5
        assert stats["distribution"] == {2: 1, 4: 2, 5: 1, 3: 1}
        # h1 重测一致（分差 0）；h2 分差 2 → 超限作废标记
        assert stats["retest_pairs"] == 2
        assert stats["retest_consistent"] == 1
        assert sorted(stats["retest_invalidated"]) == ["h2"]

    def test_stats_empty(self, tmp_path: Path) -> None:
        stats = anchor_stats(tmp_path / "missing.jsonl")
        assert stats["n"] == 0
        assert stats["retest_pairs"] == 0


class TestLoadScoredHashes:
    def test_loads_distinct_hashes(self, tmp_path: Path) -> None:
        out = tmp_path / "anchors.jsonl"
        append_anchor(out, {"report_hash": "h1", "score": 4, "reason": "x", "is_retest": False})
        append_anchor(out, {"report_hash": "h1", "score": 4, "reason": "retest", "is_retest": True})
        assert load_scored_hashes(out) == {"h1"}

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_scored_hashes(tmp_path / "nope.jsonl") == set()


class TestAnchorItemContract:
    def test_item_fields(self) -> None:
        it = AnchorItem(path=Path("x.md"), hash="abc", display="abc", is_retest=False)
        assert it.display == "abc" and not it.is_retest
