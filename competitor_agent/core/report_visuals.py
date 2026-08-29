"""可视化导出（设计文档 67 §3.1）— 雷达图 / 单文件自包含 HTML 分享

- ``render_radar``：六维置信度雷达图，**matplotlib 为可选依赖**（pyproject optional
  extra ``visuals = ["matplotlib>=3.7"]``），缺失时返回 None 并记日志（降级不炸）；
- ``render_html``：单文件自包含 HTML——内嵌 CSS + 报告 markdown 正文 + 结构化数据
  （``report_to_dict``），用 `marked` CDN 走 static/ 现有渲染思路，**离线内嵌一份**
  （拷贝 static/vendor/marked.min.js + DOMPurify.min.js，缺文件时降级为极简
  本地 markdown→HTML 转换，不依赖外网资源）。

生成 <data_dir>/reports/competitor/<name>.html / comparison/<names>.html。
"""
from __future__ import annotations

import html
import json
import logging
import math
import re
from pathlib import Path
from typing import Any

from competitor_agent.core.report_archiver import _safe_filename, resolve_output_dir
from competitor_agent.core.report_exporter import report_to_dict
from competitor_agent.domain_types.report import ComparisonReport, CompetitorReport
from competitor_agent.secret_vault import get_reports_dir

logger = logging.getLogger("competitor_agent.core.report_visuals")

# 六维雷达轴（缺维度的竞品该轴为 0，标注"无数据"）
_RADAR_DIMENSIONS = ["pricing", "feature", "performance", "ecosystem", "sentiment", "roadmap"]

_CSS = """
:root{--bg:#0f1115;--panel:#171a21;--text:#e6e8ec;--muted:#8b93a1;--accent:#4f8cff;--border:#262b36}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.7}
.wrap{max-width:880px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:26px;border-bottom:1px solid var(--border);padding-bottom:12px}
h2{font-size:19px;margin-top:32px;color:var(--accent)}
h3{font-size:16px}code{background:var(--panel);border:1px solid var(--border);padding:1px 6px;border-radius:4px}
pre{background:var(--panel);border:1px solid var(--border);padding:14px;border-radius:8px;overflow:auto}
blockquote{border-left:3px solid var(--accent);margin:12px 0;padding:2px 14px;color:var(--muted)}
a{color:var(--accent)}table{border-collapse:collapse;width:100%;margin:12px 0}
th,td{border:1px solid var(--border);padding:6px 10px;text-align:left}th{background:var(--panel)}
ul,ol{padding-left:22px}.meta{color:var(--muted);font-size:13px;margin-bottom:24px}
.badge{display:inline-block;background:var(--panel);border:1px solid var(--border);border-radius:20px;padding:2px 12px;font-size:12px;color:var(--muted);margin-right:8px}
"""


def _markdown_to_html(text: str) -> str:
    """极简离线 markdown→HTML（降级路径，无 marked/DOMPurify 时用）。

    覆盖常见语法：标题/列表/表格/引用/代码块/行内 code/粗斜体/链接/分隔线。
    """
    lines = (text or "").splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # 代码块
        if stripped.startswith("```"):
            i += 1
            buf: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(html.escape(lines[i]))
                i += 1
            out.append("<pre>" + "<br>".join(buf) + "</pre>")
            i += 1
            continue
        # 表格
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|?\s*$", lines[i + 1]):
            header = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            out.append("<table><thead><tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in header) + "</tr></thead><tbody>")
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                out.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>")
                i += 1
            out.append("</tbody></table>")
            continue
        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{html.escape(m.group(2))}</h{level}>")
            i += 1
            continue
        # 分隔线
        if re.match(r"^(\*\*\*|---|___)\s*$", stripped):
            out.append("<hr>")
            i += 1
            continue
        # 列表
        if re.match(r"^[-*+]\s+", stripped) or re.match(r"^\d+\.\s+", stripped):
            ordered = bool(re.match(r"^\d+\.\s+", stripped))
            out.append("<ol>" if ordered else "<ul>")
            while i < len(lines):
                item = lines[i].strip()
                if re.match(r"^[-*+]\s+", item):
                    out.append(f"<li>{_inline(html.escape(item[2:].lstrip()))}</li>")
                elif re.match(r"^\d+\.\s+", item):
                    body = re.sub(r"^\d+\.\s+", "", item)
                    out.append(f"<li>{_inline(html.escape(body))}</li>")
                else:
                    break
                i += 1
            out.append("</ol>" if ordered else "</ul>")
            continue
        # 引用
        if stripped.startswith(">"):
            out.append(f"<blockquote>{html.escape(stripped.lstrip('>').strip())}</blockquote>")
            i += 1
            continue
        if stripped:
            out.append(f"<p>{_inline(html.escape(stripped))}</p>")
        else:
            out.append("")
        i += 1
    return "\n".join(out)


def _inline(text: str) -> str:
    """行内格式化（在 HTML 转义后调用）：code/粗体/斜体/链接。"""
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    return text


def _embedded_vendor(name: str) -> str:
    """从 static/vendor 读取离线内嵌 JS（marked/DOMPurify），缺文件返回空串。"""
    try:
        from importlib import resources

        return (resources.files("competitor_agent") / "static" / "vendor" / name).read_text(
            encoding="utf-8"
        )
    except Exception:  # noqa: BLE001 - vendor 文件缺失走离线降级
        logger.debug("static/vendor/%s 缺失，走离线极简渲染", name)
        return ""


def render_html_doc(
    markdown: str,
    structured: dict[str, Any],
    *,
    title: str,
    created_at: str,
    out_path: str | Path,
) -> Path:
    """单文件自包含 HTML 渲染核心（render_html 与 CLI report --html 共用）。

    内嵌 CSS + markdown 正文 + 结构化数据 + 离线内嵌 marked/DOMPurify（缺文件
    降级为极简本地 markdown→HTML）。返回落盘路径。
    """
    marked_js = _embedded_vendor("marked.min.js")
    dompurify_js = _embedded_vendor("dompurify.min.js")
    render_script = (
        "<script>window.addEventListener('DOMContentLoaded',function(){"
        "var raw=document.getElementById('raw'),t=document.getElementById('content');"
        "if(window.marked&&window.DOMPurify){t.innerHTML=DOMPurify.sanitize("
        "marked.parse(raw.textContent));}});</script>"
        if marked_js and dompurify_js
        else _markdown_to_html(markdown)
    )
    body_html = (
        f"<pre id=\"raw\" style=\"display:none\">{html.escape(markdown)}</pre>"
        f"<div id=\"content\"></div>{render_script}"
        if marked_js and dompurify_js
        else f"<div id=\"content\">{render_script}</div>"
    )

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} — 竞品分析报告</title>
<style>{_CSS}</style></head>
<body><div class="wrap">
<h1>{html.escape(title)}</h1>
<div class="meta">
  <span class="badge">自包含报告</span>
  <span class="badge">生成于 {html.escape(str(created_at))}</span>
</div>
<div id="content">{body_html}</div>
<script id="data" type="application/json">{html.escape(json.dumps(structured, ensure_ascii=False))}</script>
{marked_js}{dompurify_js}</div></body></html>"""

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    from competitor_agent.core.checkpoint import _write_bytes_atomic

    _write_bytes_atomic(path, html_doc.encode("utf-8"))
    logger.info("HTML 已导出: %s", path)
    return path


def render_html(
    report: CompetitorReport | ComparisonReport,
    out_path: str | Path | None = None,
) -> Path:
    """单文件自包含 HTML：内嵌 CSS + markdown 正文 + 结构化数据 + 离线 marked。

    ``out_path`` 缺省：单竞品 → <data_dir>/reports/competitor/<name>.html；
    对比 → <data_dir>/reports/comparison/<names>.html。返回落盘路径。
    """
    if isinstance(report, ComparisonReport):
        name = " / ".join(c.name for c in report.competitors) or "compare"
        structured = {
            "schema_version": "1.0.0",
            "competitors": [c.name for c in report.competitors],
            "created_at": report.created_at,
        }
    else:
        name = report.competitor.name
        structured = report_to_dict(report)

    return render_html_doc(
        report.markdown_report,
        structured,
        title=name,
        created_at=str(report.created_at),
        out_path=_resolve_html_path(report, out_path),
    )


def _resolve_html_path(
    report: CompetitorReport | ComparisonReport,
    out_path: str | Path | None,
) -> Path:
    """HTML 落盘路径：显式 out_path > 默认（单竞品 competitor/ 对比 comparison/）。"""
    if out_path is not None:
        p = Path(out_path).expanduser()
        return p if p.is_absolute() else Path.cwd() / p
    if isinstance(report, ComparisonReport):
        base = resolve_output_dir(load_config_reports_dir("comparison"))
    else:
        base = resolve_output_dir()
    name = " / ".join(c.name for c in report.competitors) if isinstance(report, ComparisonReport) else report.competitor.name
    return base / (_safe_filename(name) + ".html")


def load_config_reports_dir(section: str) -> str:
    """读取 config 报告目录（'competitor' | 'comparison'）。"""
    from competitor_agent.config.loader import load_config

    cfg = load_config().report
    return cfg.output_dir if section == "competitor" else cfg.comparison_dir


def render_radar(
    report: ComparisonReport,
    out_path: str | Path | None = None,
) -> Path | None:
    """六维置信度雷达图（matplotlib 可选依赖；缺失 → None 并记日志，降级不炸）。

    ``out_path`` 缺省 → <data_dir>/reports/comparison/<names>.png。
    """
    try:
        # 经 importlib 加载 matplotlib（可选依赖）：字面 import matplotlib 会触发
        # 本环境 mypy 的 serialize 内部崩溃（unresolved placeholder type None），
        # importlib.import_module 让 mypy 无从分析该导入；缺失 → 降级返回 None 不炸。
        import importlib

        matplotlib_mod = importlib.import_module("matplotlib")
        matplotlib_mod.use("Agg")
        plt = importlib.import_module("matplotlib.pyplot")
    except Exception as exc:  # noqa: BLE001
        logger.warning("雷达图渲染跳过（matplotlib 不可用）: %s", exc)
        return None

    dims = _RADAR_DIMENSIONS
    # 六维角度用纯标准库计算（避免 numpy 局部导入触发 mypy 内部崩溃；matplotlib 仍可选依赖）
    angles = [2 * math.pi * i / len(dims) for i in range(len(dims))]
    angles += angles[:1]

    fig: Any = None
    ax: Any = None
    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw={"polar": True})
    for r in report.reports:
        # 每个竞品：维度结果 → 六维置信度
        confidences = {dr.dimension: float(dr.confidence or 0.0) for dr in r.dimension_results}
        values = [confidences.get(d, 0.0) for d in dims]
        values += values[:1]
        ax.plot(angles, values, label=r.competitor.name)
        ax.fill(angles, values, alpha=0.08)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(dims)
    ax.set_ylim(0, 1)
    ax.set_title("维度置信度对比", pad=20)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1))
    fig.tight_layout()

    if out_path is not None:
        path = Path(out_path).expanduser()
    else:
        path = get_reports_dir() / "comparison"
    if path.is_dir() or out_path is None:
        names = " / ".join(c.name for c in report.competitors) or "compare"
        path = path / (_safe_filename(names) + ".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("雷达图已导出: %s", path)
    return path


__all__ = ["render_html", "render_html_doc", "render_radar"]
