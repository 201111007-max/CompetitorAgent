"""结构化导出（设计文档 28 §3.1）

每次分析产出 ``<data_dir>/reports/competitor/<竞品>.json``（与 .md 同目录同名不同扩展名）：
机器可读的 competitor / dimensions / evidence / freshness / pricing.profile /
benchmark_scores；比较报告另出 ``<output>/comparison/<names>.json``（品类矩阵数据，
设计文档 70 §8.2 D2a：恒派生自 resolve_output_dir 的 /comparison 子目录）。

复用 checkpoint 的原子写模式（临时文件 + fsync + os.replace）与 report_archiver
的路径解析/文件名净化，与 ``report_archiver``（.md）并存不冲突。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from competitor_agent.core.checkpoint import _write_bytes_atomic
from competitor_agent.core.report_archiver import (
    _safe_filename,
    resolve_comparison_dir,
    resolve_output_dir,
)
from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.domain_types.report import (
    ComparisonReport,
    CompetitorReport,
    DimensionResult,
)

REPORT_SCHEMA_VERSION = "1.0.0"


def _dimension_to_dict(result: object) -> dict[str, Any]:
    """单维度 → 稳定 schema：field/status/confidence/summary/evidence[{url,trust}]。"""
    evidence = [
        {
            "url": str(getattr(e, "url", "")),
            "trust": round(float(getattr(e, "trust_level", 0.0) or 0.0), 3),
        }
        for e in (getattr(result, "evidence", None) or [])
        if getattr(e, "url", "")
    ]
    status = getattr(result, "status", None)
    return {
        "field": str(getattr(result, "dimension", "")),
        "status": status.value if status is not None and hasattr(status, "value") else str(status),
        "confidence": round(float(getattr(result, "confidence", 0.0) or 0.0), 3),
        "summary": str(getattr(result, "summary", "") or ""),
        "evidence": evidence,
    }


def _pricing_profile(report: CompetitorReport) -> dict[str, Any] | None:
    """从 pricing 维度结果的 details（49 命名空间 plans）提取结构化定价画像。"""
    for r in report.dimension_results:
        if r.dimension != "pricing":
            continue
        details = getattr(r, "details", None)
        if not isinstance(details, dict):
            continue
        from competitor_agent.domain_types.pricing import profile_from_details

        profile = profile_from_details(details, getattr(r, "evidence", None) or [])
        if profile.has_pricing_data:
            return profile.to_dict()
    return None


def _benchmark_scores(report: CompetitorReport) -> list[dict[str, Any]]:
    """从 performance 维度结果的 details["benchmarks"] 提取榜单分数。"""
    for r in report.dimension_results:
        if r.dimension != "performance":
            continue
        details = getattr(r, "details", None)
        if isinstance(details, dict) and isinstance(details.get("benchmarks"), list):
            return [b for b in details["benchmarks"] if isinstance(b, dict)]
    return []


def report_to_dict(report: CompetitorReport, approval_status: str = "approved") -> dict[str, Any]:
    """稳定导出 schema：competitor / dimensions / freshness / pricing.profile /
    benchmark_scores / created_at / terminal_state / status（设计文档 67 §3.2）。

    schema 版本号随 REPORT_SCHEMA_VERSION（语义同 HARNESS_VERSION），
    供下游工具做字段兼容判定。``approval_status`` 由审批门决定
    （approved / pending_review / rejected），缺省 approved（无审批 → 直通发布）。
    """
    freshness = report.freshness
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "competitor": report.competitor.name,
        "terminal_state": report.terminal_state,
        "overall_score": round(float(report.overall_score or 0.0), 3),
        "overall_confidence": round(float(report.overall_confidence or 0.0), 3),
        "created_at": report.created_at,
        "dimensions": [_dimension_to_dict(r) for r in report.dimension_results],
        "freshness": freshness.to_dict() if freshness is not None else None,
        "pricing": _pricing_profile(report),
        "benchmark_scores": _benchmark_scores(report),
        "gaps_pending": [str(g.field) for g in report.gaps_pending],
        "status": approval_status,
        "reviewed_at": None,
        "reviewer_note": "",
    }


def export_competitor_json(
    report: CompetitorReport,
    output_dir: str | Path | None = None,
    approval_status: str = "approved",
) -> Path:
    """原子写 <data_dir>/reports/competitor/<竞品>.json，返回落盘路径。

    ``output_dir`` 缺省取 config.report.output_dir（与 .md 同名同目录）；
    ``approval_status`` 为审批门决定的状态（设计文档 67 §3.2）。
    """
    out_dir = resolve_output_dir(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (_safe_filename(report.competitor.name) + ".json")
    data = json.dumps(
        report_to_dict(report, approval_status=approval_status),
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    _write_bytes_atomic(path, data)
    return path


def _comparison_matrix(report: ComparisonReport) -> dict[str, Any]:
    """比较报告 → {matrix, best_per_dimension, summary}（品类格局矩阵数据）。"""
    names = [c.name for c in report.competitors]
    dims_by_rep = [{r.dimension: r for r in r.dimension_results} for r in report.reports]
    all_dims = list(dict.fromkeys(d for dmap in dims_by_rep for d in dmap))

    matrix: list[dict[str, Any]] = []
    best_per_dim: dict[str, dict[str, Any]] = {}
    for dim in all_dims:
        row: dict[str, Any] = {"dimension": dim, "values": {}, "best": ""}
        for name, dmap in zip(names, dims_by_rep):
            r = dmap.get(dim)
            row["values"][name] = round(float(r.confidence), 3) if r is not None else None
        best_name, best_conf, best_status, best_summary = _best_for_dim(dim, report.reports, dims_by_rep)
        row["best"] = best_name
        best_per_dim[dim] = {
            "competitor": best_name,
            "confidence": round(float(best_conf), 3),
            "status": best_status.value if hasattr(best_status, "value") and best_status else None,
            "summary": best_summary,
        }
        matrix.append(row)

    ranked = sorted(
        ((r.competitor.name, float(r.overall_confidence or 0.0)) for r in report.reports),
        key=lambda x: x[1],
        reverse=True,
    )
    summary = {
        "competitors": names,
        "ranking": [{"competitor": n, "overall_confidence": round(c, 3)} for n, c in ranked],
        "coverage_gaps": {
            name: [d for d in all_dims if d not in dmap]
            for name, dmap in zip(names, dims_by_rep)
            if any(d not in dmap for d in all_dims)
        },
    }
    return {"matrix": matrix, "best_per_dimension": best_per_dim, "summary": summary}


def _best_for_dim(
    dim: str,
    reports: list[CompetitorReport],
    dims_by_rep: list[dict[str, DimensionResult]],
) -> tuple[str, float, ResultStatus | None, str]:
    """维度最佳：状态排序（OK > PARTIAL > N/A）+ 置信度（与 MarkdownRenderer 一致）。"""
    rank = {ResultStatus.COMPLETE: 3, ResultStatus.PARTIAL: 2, ResultStatus.UNAVAILABLE: 1}
    best: tuple[str, float, ResultStatus | None, str] | None = None
    for report, dmap in zip(reports, dims_by_rep):
        r = dmap.get(dim)
        if r is None:
            continue
        status = r.status
        rk = rank.get(status, 0)
        conf = float(r.confidence or 0.0)
        if best is None:
            best = (report.competitor.name, conf, status, str(r.summary or ""))
            continue
        best_rk = rank.get(best[2], 0) if best[2] is not None else 0
        if rk > best_rk or (rk == best_rk and conf > best[1]):
            best = (report.competitor.name, conf, status, str(r.summary or ""))
    return best if best is not None else ("", 0.0, None, "")


def export_comparison_json(
    report: ComparisonReport,
    output_dir: str | Path | None = None,
) -> Path:
    """原子写 <data_dir>/reports/comparison/<names>.json：matrix + best_per_dimension + summary。

    ``output_dir`` 缺省取 ``resolve_comparison_dir()``（设计文档 70 §8.2 D2a：恒派生自
    ``resolve_output_dir()`` 的 ``/comparison`` 子目录，不再读 config.report.comparison_dir）；
    显式传入（测试/CLI）→ 精确路径，不回退（保持向后兼容）。
    """
    out_dir = (
        resolve_comparison_dir()
        if output_dir is None
        else Path(output_dir).expanduser()
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    names = " / ".join(c.name for c in report.competitors) or "compare"
    path = out_dir / (_safe_filename(names) + ".json")
    data = json.dumps(
        {
            "schema_version": REPORT_SCHEMA_VERSION,
            "competitors": [c.name for c in report.competitors],
            "created_at": report.created_at,
            **_comparison_matrix(report),
        },
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    _write_bytes_atomic(path, data)
    return path


__all__ = [
    "REPORT_SCHEMA_VERSION",
    "export_comparison_json",
    "export_competitor_json",
    "report_to_dict",
]
