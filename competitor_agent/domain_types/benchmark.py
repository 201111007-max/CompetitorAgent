"""BenchmarkScore — 榜单直连的权威性能分数（设计文档 25）

供 BenchmarkSourceProvider 产出、PerformanceAnalyzer 合并（榜单优先）。
retrieved_at 供设计文档 26（新鲜度/时间线）消费。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkScore:
    """一条榜单分数：board / metric / score / unit / retrieved_at / source_url"""

    board: str            # "swe_bench_verified"
    board_label: str      # "SWE-bench Verified"
    metric: str           # "score"（预留指标名，如 "resolve rate" / "pass@1"）
    score: float
    unit: str             # "%" / "elo" / ""
    retrieved_at: str     # ISO 时间戳
    source_url: str
