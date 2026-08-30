"""报告落盘归档 — 原子写 <输出目录>/<竞品>.md（设计文档 22 §3.2 / 70）

复用 checkpoint 的原子写模式（临时文件 + fsync + os.replace），避免写一半损坏。
Web / CLI 共用，消除重复；与 archive_session（L1 记忆）并存，落盘为额外导出。
目录解析（设计文档 70）：显式 output_dir > settings.json > config.report.output_dir
（YAML 置空则跳过）> 项目默认 output/；下载目录默认 <项目根>/download（可被
settings.json 覆盖）；旧归档（~/.competitor_agent/reports/competitor）读侧回退不迁移。
"""
from __future__ import annotations

import re
from pathlib import Path

from competitor_agent.config.loader import load_config
from competitor_agent.core.checkpoint import _write_bytes_atomic
from competitor_agent.core.report_settings import (
    default_download_dir,
    default_output_dir,
    get_setting,
)
from competitor_agent.domain_types.report import ComparisonReport, CompetitorReport

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9_.\-一-鿿]+")

# 历史归档目录（设计文档 70 前的默认落盘点：~/.competitor_agent/reports/competitor），
# 读侧回退不迁移（设计文档 70 §7 #5：旧报告仍可开/下载，零风险）
_LEGACY_REPORTS_DIR = Path("~/.competitor_agent/reports/competitor").expanduser()


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
    """解析报告输出目录（设计文档 70：优先级 显式 > settings > yaml（空跳过）> 项目 output/）。

    支持 ``~`` 展开；相对路径按 CWD 解析。显式传入时行为不变（测试/CLI 兼容）。
    """
    raw: str | Path
    if output_dir is not None:
        raw = output_dir
    else:
        raw = get_setting("report_output_dir") or load_config().report.output_dir or ""
    if not str(raw).strip():
        return default_output_dir()
    path = Path(raw).expanduser()
    return path if path.is_absolute() else Path.cwd() / path


def resolve_download_dir() -> Path:
    """解析下载目录：settings.report_download_dir 非空用之，否则 <项目根>/download。"""
    raw = get_setting("report_download_dir")
    if not str(raw).strip():
        return default_download_dir()
    path = Path(raw).expanduser()
    return path if path.is_absolute() else Path.cwd() / path


def resolve_comparison_dir(output_dir: str | Path | None = None) -> Path:
    """解析对比矩阵 JSON 目录（设计文档 70 §8.2 D2a）：恒派生自 ``resolve_output_dir()`` 的
    ``/comparison`` 子目录。不读 config.report.comparison_dir、不读 settings（无新配置键）。

    ``output_dir`` 显式传入时（测试/CLI）基于其派生 ``/comparison``。旧 comparison 目录
    （~/.competitor_agent/reports/comparison）读侧回退不迁移（设计文档 70 §8.2 D2c）。
    """
    return resolve_output_dir(output_dir) / "comparison"


def _fallback_legacy_path(fname: str) -> Path:
    """旧归档目录路径（读侧回退用，不迁移）。"""
    return _LEGACY_REPORTS_DIR / fname


def save_report_markdown(
    report: CompetitorReport | ComparisonReport,
    output_dir: str | Path | None = None,
    filename: str | None = None,
) -> Path:
    """原子写报告到 <输出目录>/<竞品>.md，返回落盘路径。"""
    name, markdown = _report_identity(report)
    if not markdown:
        raise ValueError(f"报告为空，无法落盘（竞品: {name}）")
    out_dir = resolve_output_dir(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = _safe_filename(filename or name) + ".md"
    path = out_dir / fname
    _write_bytes_atomic(path, markdown.encode("utf-8"))
    return path


def save_report_download(
    report: CompetitorReport | ComparisonReport,
    download_dir: str | Path | None = None,
) -> Path:
    """把报告 .md 原子写进下载目录（设计文档 70），返回落盘路径。"""
    name, markdown = _report_identity(report)
    if not markdown:
        raise ValueError(f"报告为空，无法落盘（竞品: {name}）")
    out_dir = Path(download_dir) if download_dir is not None else resolve_download_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (_safe_filename(name) + ".md")
    _write_bytes_atomic(path, markdown.encode("utf-8"))
    return path


def report_file_path(
    competitor: str,
    output_dir: str | Path | None = None,
) -> Path:
    """Web /api/reports/{competitor} 的落盘路径解析（与 save_report_markdown 命名一致）。

    设计文档 70：新目录优先；未显式指定目录时旧归档
    （~/.competitor_agent/reports/competitor）读侧回退（历史报告不迁移不丢）。
    显式 output_dir（测试/CLI）→ 精确路径，不回退。均不存在 → 返回新目录路径（由端点 404）。
    """
    primary = resolve_output_dir(output_dir) / (_safe_filename(competitor) + ".md")
    if primary.exists():
        return primary
    if output_dir is None:
        legacy = _fallback_legacy_path(_safe_filename(competitor) + ".md")
        if legacy.exists():
            return legacy
    return primary


def download_file_path(
    competitor: str,
    output_dir: str | Path | None = None,
) -> Path:
    """下载路径解析（设计文档 70）：下载目录优先 → 归档目录（含旧归档回退）。"""
    primary = resolve_download_dir() / (_safe_filename(competitor) + ".md")
    if primary.exists():
        return primary
    return report_file_path(competitor, output_dir=output_dir)


__all__ = [
    "download_file_path",
    "report_file_path",
    "resolve_comparison_dir",
    "resolve_download_dir",
    "resolve_output_dir",
    "save_report_download",
    "save_report_markdown",
]
