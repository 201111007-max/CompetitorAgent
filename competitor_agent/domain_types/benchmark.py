"""BenchmarkScore — 榜单直连的权威性能分数（设计文档 25）

供 BenchmarkSourceProvider 产出、PerformanceAnalyzer 合并（榜单优先）。
retrieved_at 供设计文档 26（新鲜度/时间线）消费。

跑分口径 provenance 助手（设计文档 80）：把「数据可信」做成系统级能力——
source_type（厂商自报 vs 第三方实测）/ scaffold / 模型版本 / 采集时间全链路显式标注；
**留空即诚实**（解析不到的口径留空并在展示层显式「口径未声明」，doc 47 纪律）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 口径来源类型 → 展示文案
_SOURCE_TYPE_LABELS = {
    "third_party": "第三方实测",
    "vendor_self_reported": "厂商自报",
}


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


def provenance_note(
    source_type: str = "",
    provider_name: str = "",
    scaffold_version: str = "",
    model_version: str = "",
    collected_at: str = "",
) -> str:
    """口径尾注：`[口径: 第三方实测·swebench·scaffold=v2.1·model=…·collected=…date]`。

    未声明字段省略；全部未声明 → `[口径未声明]`（留空即诚实，不编造）。
    """
    parts: list[str] = []
    label = _SOURCE_TYPE_LABELS.get(str(source_type or ""), "")
    if label:
        parts.append(label)
    if provider_name:
        parts.append(str(provider_name))
    if scaffold_version:
        parts.append(f"scaffold={scaffold_version}")
    if model_version:
        parts.append(f"model={model_version}")
    if collected_at:
        parts.append(f"collected={str(collected_at)[:10]}")
    if not parts:
        return "[口径未声明]"
    return "[口径: " + "·".join(parts) + "]"


def provenance_note_from_entry(entry: Any) -> str:
    """从 benchmarks 条目（dict，含 source_type/provider_name/…/fetched_at）构建口径尾注。"""
    if not isinstance(entry, dict):
        return "[口径未声明]"
    return provenance_note(
        source_type=str(entry.get("source_type") or ""),
        provider_name=str(entry.get("provider_name") or ""),
        scaffold_version=str(entry.get("scaffold_version") or ""),
        model_version=str(entry.get("model_version") or ""),
        collected_at=str(entry.get("fetched_at") or entry.get("collected_at") or ""),
    )


def provenance_complete(entry: Any) -> bool:
    """口径是否完整（source_type 与 model_version 均声明）——score_change 告警降级判据（doc 80 §2.2）。"""
    if not isinstance(entry, dict):
        return False
    return bool(entry.get("source_type")) and bool(entry.get("model_version"))


def first_benchmark_entry(details: Any) -> Any:
    """从 performance 维度 details（{"benchmarks": [...]}) 取首个跑分条目；无 → None。"""
    if not isinstance(details, dict):
        return None
    benchmarks = details.get("benchmarks")
    if isinstance(benchmarks, list) and benchmarks:
        return benchmarks[0]
    return None


def has_vendor_self_reported(details: Any) -> bool:
    """performance details 是否含厂商自报口径条目（渲染 ⚠ 引导行判据）。"""
    if not isinstance(details, dict):
        return False
    benchmarks = details.get("benchmarks")
    if not isinstance(benchmarks, list):
        return False
    return any(
        isinstance(b, dict) and str(b.get("source_type") or "") == "vendor_self_reported"
        for b in benchmarks
    )

