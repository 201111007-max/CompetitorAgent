"""人工锚点评分工具（设计文档 83 §4.4，工单 12/3）。

纯函数层：报告池收集（排除已打分 / 盲评脱敏 / 确定性洗牌 / 重测混入）、
条目校验（理由必填、分数 1~5）、jsonl 追加与统计（分分布 / 重测一致率 / 分差>1 作废）。

公平性机制对应（doc 83 §4.3）：
- 盲评：``display`` 恒为内容短 hash，不泄漏文件名/生成时间；顺序由 seed 确定性洗牌。
- 重测混入：已打分报告按 ``retest_rate`` 抽回，``is_retest=True`` 盲态混入。
- 理由必填与分数域校验：``validate_entry``，无理由分数不计入锚点集。
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# 重测一致判定：同一报告前后分差 ≤1 视为一致（>1 两次分数均作废，doc 83 §4.3 第 3 条）
_RETEST_DIFF_LIMIT = 1


def _stats_empty() -> dict:
    return {
        "n": 0,
        "distribution": {},
        "retest_pairs": 0,
        "retest_consistent": 0,
        "retest_invalidated": [],
    }


@dataclass
class AnchorItem:
    """待打分条目：``display`` 为盲评展示名（= 内容短 hash）。"""

    path: Path
    hash: str
    display: str
    is_retest: bool = False


def report_hash(path: Path) -> str:
    """报告内容短 hash（12 hex）：同内容同 hash（盲评靠它跨周关联重测），与文件名无关。"""
    content = path.read_bytes()
    return hashlib.sha256(content).hexdigest()[:12]


def collect_pool(
    pool: list[Path],
    scored_hashes: set[str] | None = None,
    retest_rate: float = 0.0,
    seed: int = 0,
    blind: bool = True,
) -> list[AnchorItem]:
    """收集待打分条目：排除已打分 → 按 ``retest_rate`` 抽回重测 → 盲评洗牌。

    盲评（默认 ``blind=True``）：展示名恒为内容 hash，``is_retest=True`` 条目盲态
    混入，打分者不可分辨，顺序为 seed 确定性洗牌；``--no-blind``（``blind=False``）
    展示真实文件名且保持池顺序（不打乱），``is_retest`` 标记保留供统计。
    """
    scored = scored_hashes or set()
    unscored = [p for p in pool if report_hash(p) not in scored]
    retest_pool = [p for p in pool if report_hash(p) in scored]
    k = round(len(retest_pool) * retest_rate)
    k = max(0, min(k, len(retest_pool)))
    retests = random.Random(seed).sample(retest_pool, k) if k else []

    def _display(p: Path) -> str:
        return p.name if not blind else report_hash(p)

    items = [AnchorItem(path=p, hash=report_hash(p), display=_display(p), is_retest=True) for p in retests]
    items += [AnchorItem(path=p, hash=report_hash(p), display=_display(p), is_retest=False) for p in unscored]
    if blind:  # --no-blind：实名展示 + 保持池顺序（不打乱）
        random.Random(seed).shuffle(items)
    return items


def validate_entry(score: int, reason: str) -> str | None:
    """条目校验：返回 None 表示有效，否则返回可读错误（理由必填 + 分数 1~5）。"""
    if not isinstance(score, int) or isinstance(score, bool) or score < 1 or score > 5:
        return "分数须为 1~5 的整数"
    if not reason or not reason.strip():
        return "理由必填（无理由分数不计入锚点集）"
    return None


def append_anchor(out: Path, entry: dict) -> None:
    """追加一条锚点记录（JSONL，UTF-8，ensure_ascii=False 保留中文理由）。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _read_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            entries.append(obj)
    return entries


def load_scored_hashes(path: Path) -> set[str]:
    """已打分报告 hash 集合（含重测条目——同一报告只算已打分）。"""
    return {str(e["report_hash"]) for e in _read_entries(path) if e.get("report_hash")}


def anchor_stats(path: Path) -> dict:
    """锚点统计：样本量 / 分分布 / 重测一致率（分差>1 的报告两次分数均标记作废）。"""
    entries = _read_entries(path)
    if not entries:
        return _stats_empty()

    distribution: Counter = Counter()
    by_hash: dict[str, dict[bool, int]] = {}
    for e in entries:
        raw_score = e.get("score")
        if raw_score is None:
            continue
        try:
            score = int(raw_score)
        except (TypeError, ValueError):
            continue
        distribution[score] += 1
        h = str(e.get("report_hash") or "")
        if not h:
            continue
        is_retest = bool(e.get("is_retest"))
        slot = by_hash.setdefault(h, {False: 0, True: 0})
        if slot[is_retest] == 0:
            slot[is_retest] = score

    pairs = 0
    consistent = 0
    invalidated: list[str] = []
    for h, slot in by_hash.items():
        if not (slot[False] and slot[True]):
            continue
        pairs += 1
        diff = abs(slot[True] - slot[False])
        if diff <= _RETEST_DIFF_LIMIT:
            consistent += 1
        else:
            invalidated.append(h)

    return {
        "n": len(entries),
        "distribution": dict(sorted(distribution.items())),
        "retest_pairs": pairs,
        "retest_consistent": consistent,
        "retest_invalidated": sorted(invalidated),
    }
