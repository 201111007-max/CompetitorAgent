"""报告落盘归档 — 原子写 reports/competitor/<竞品>.md（设计文档 22 §3.2）

复用 checkpoint 的原子写模式（临时文件 + fsync + os.replace），避免写一半损坏。
Web / CLI 共用，消除重复；与 archive_session（L1 记忆）并存，落盘为额外导出。
"""
from __future__ import annotations

import re
from pathlib import Path

from competitor_agent.config.loader import AppConfig, load_config
from competitor_agent.core.checkpoint import _write_bytes_atomic
from competitor_agent.domain_types.report import CompetitorReport, ComparisonReport

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9_.\-一-鿿]+")


def _report_identity(report: CompetitorReport | ComparisonReport) -> tuple[str, str]:
    """提取 (竞品名, markdown 正文)：单竞品取 competitor.name，对比取 'A / B' 联合名。"""
    if isinstance(report, ComparisonReport):
        name = " / ".join(c.name for c in report.competitors) or "compare"
    else:
        name = report.competitor.name
    return name, report.markdown_report


def _safe_filename(name: str) -> str:
    """文件名净化：去掉路径分隔符与危险字符，防路径穿越。"""
    name = name.replace("/", "_").replace("\\", "_")
    name = _SAFE_CHARS.sub("_", name).strip("._")
    return name or "report"


def resolve_output_dir(output_dir: str | Path | None = None) -> Path:
    """解析报告输出目录：未显式给出时取 AppConfig.report.output_dir，相对路径按 CWD 解析。"""
    raw: str | Path
    if output_dir is not None:
        raw = output_dir
    else:
        raw = load_config().report.output_dir
    path = Path(raw).expanduser()
    return path if path.is_absolute() else Path.cwd() / path


def save_report_markdown(
    report: CompetitorReport | ComparisonReport,
    output_dir: str | Path | None = None,
    filename: str | None = None,
) -> Path:
    """原子写报告到 reports/competitor/<竞品>.md，返回落盘路径。"""
    name, markdown = _report_identity(report)
    if not markdown:
        raise ValueError(f"报告为空，无法落盘（竞品: {name}）")
    out_dir = resolve_output_dir(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = _safe_filename(filename or name) + ".md"
    path = out_dir / fname
    _write_bytes_atomic(path, markdown.encode("utf-8"))
    return path


def report_file_path(
    competitor: str,
    output_dir: str | Path | None = None,
) -> Path:
    """Web /api/reports/{competitor} 的落盘路径解析（与 save_report_markdown 命名一致）。"""
    out_dir = resolve_output_dir(output_dir)
    return out_dir / (_safe_filename(competitor) + ".md")


__all__ = [
    "report_file_path",
    "resolve_output_dir",
    "save_report_markdown",
]
