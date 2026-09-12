"""评测指标版本化（设计文档 76 §2.4，工单 4）。

benchmark 每次运行产出带 commit hash 的指标快照，追加 ``evals/history.jsonl``
（纳入 git），``eval-diff`` 对比任意两版（commit 短 hash 或 latest/N）。

快照只收数字 + commit + harness 版本，保证 diff 是纯函数可计算；
``judge_spearman`` 占位 None（doc 83 校准后回填）。
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 仓库根 evals/history.jsonl（evaluation/history.py → competitor_agent 包 → 仓库根）
DEFAULT_HISTORY_PATH = Path(__file__).resolve().parents[2] / "evals" / "history.jsonl"


def git_head() -> str:
    """当前 commit 短 hash；不在 git 仓库/命令失败 → "unknown"。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def snapshot(
    report: Any,
    *,
    commit: str | None = None,
    wall_seconds: float | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    """从 BenchmarkReport 提取指标快照（只收数字，保证 diff 可计算）。

    ``tag`` 记录用例子集口径（benchmark --tag）——不同子集的快照不可直接 diff，
    口径标注让 eval-diff 的可比性可审计。
    """
    metrics: dict[str, Any] = {
        "field_accuracy": report.accuracy.field_accuracy,
        "hallucination_rate": report.accuracy.hallucination_rate,
        "f1": report.accuracy.f1,
        "tool_selection_accuracy": report.strategy.tool_selection_accuracy,
        "cost_efficiency": report.strategy.cost_efficiency,
        "trace_completeness": report.trace_completeness,
        "must_have_recall": report.golden.must_have_recall,
        "trap_pass_rate": report.golden.trap_pass_rate,
        "contradicted_count": report.golden.contradicted_count,
        "judge_spearman": None,  # doc 83 人工锚点校准后回填
        "cost_usd": report.cost_usd,
        "per_case_cost": (
            round(sum(report.per_case_cost.values()) / len(report.per_case_cost), 6)
            if report.per_case_cost
            else 0.0
        ),
        "wall_seconds": round(wall_seconds, 3) if wall_seconds is not None else None,
    }
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": commit or git_head(),
        "harness_version": report.harness_version,
        "llm_mode": report.llm_mode,
        "tag": tag,
        "n_cases": report.n_cases,
        "metrics": metrics,
    }


def append_history(path: Path | None, snap: dict[str, Any]) -> None:
    """追加一条快照（JSONL，UTF-8；父目录自动创建）。"""
    target = path or DEFAULT_HISTORY_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(snap, ensure_ascii=False) + "\n")


def load_history(path: Path | None = None) -> list[dict[str, Any]]:
    """读取全部快照（按文件顺序；坏行跳过）。"""
    target = path or DEFAULT_HISTORY_PATH
    if not target.exists():
        return []
    snaps: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            snaps.append(obj)
    return snaps


def _resolve_rev(rev: str, snaps: list[dict[str, Any]]) -> dict[str, Any]:
    """定位快照：``latest``（最新一条）/ ``latest/N``（倒数第 N 条，latest/1=latest）/
    commit 短 hash 前缀匹配。找不到 → ValueError 可读信息。"""
    if rev == "latest" or rev.startswith("latest/"):
        n = 1
        if rev != "latest":
            try:
                n = int(rev.split("/", 1)[1])
            except ValueError as exc:
                raise ValueError(f"非法快照引用: {rev}（latest/N 的 N 须为整数）") from exc
        if n < 1 or n > len(snaps):
            raise ValueError(
                f"快照引用越界: {rev}（history 共 {len(snaps)} 条）"
            )
        return snaps[-n]
    for snap in snaps:
        if str(snap.get("commit", "")).startswith(rev):
            return snap
    raise ValueError(f"未找到快照: {rev}（evals/history.jsonl 共 {len(snaps)} 条；先跑 benchmark --snapshot）")


def diff(from_rev: str, to_rev: str, path: Path | None = None) -> str:
    """对比两版快照，输出逐指标 ± Δ 表格（供 README「最近 3 版指标变化表」粘贴）。"""
    snaps = load_history(path)
    if not snaps:
        return f"（{path or DEFAULT_HISTORY_PATH} 无快照——先跑 benchmark --snapshot）"
    a = _resolve_rev(from_rev, snaps)
    b = _resolve_rev(to_rev, snaps)
    metrics_a: dict[str, Any] = a.get("metrics", {})
    metrics_b: dict[str, Any] = b.get("metrics", {})
    keys = list(dict.fromkeys([*metrics_a.keys(), *metrics_b.keys()]))
    lines = [
        (
            f"评测指标对比: {a.get('commit')}({a.get('ts')}, harness v{a.get('harness_version')})"
            f" → {b.get('commit')}({b.get('ts')}, harness v{b.get('harness_version')})"
        ),
        "",
        f"{'指标':<24}{'from':>12}{'to':>14}{'Δ':>14}",
        "-" * 64,
    ]
    for key in keys:
        va, vb = metrics_a.get(key), metrics_b.get(key)
        if va is None and vb is None:
            lines.append(f"{key:<24}{'—':>12}{'—':>14}{'—':>14}")
            continue
        sa = f"{va:.4f}" if isinstance(va, (int, float)) else str(va)
        sb = f"{vb:.4f}" if isinstance(vb, (int, float)) else str(vb)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            delta = f"{vb - va:+.4f}"
        else:
            delta = "—"
        lines.append(f"{key:<24}{sa:>12}{sb:>14}{delta:>14}")
    return "\n".join(lines)
