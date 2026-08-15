"""会话摘要压缩（设计文档 35 §3.1）

每次分析后对归档会话做结构化摘要（结论/证据/遗留缺口），长存档滚动压缩：
- ``summarize_session``：规则抽取高置信结论（无 LLM、无 Key 可复现，可选 LLM 凝练留待后续）；
- ``compress_archive``：把旧会话折叠为摘要条目（最近 ``keep_full`` 条保全文视图）。

结论抽取阈值与回退逻辑：
- 仅采纳 ``confidence >= 0.6`` 的 DimensionResult.summary 作为结论；
- 历史归档（raw 无结构化 dimensions）回退取 Markdown 首行作占位，保证可检索。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 结论抽取阈值：仅采纳高置信 DimensionResult.summary
_CONFIDENCE_THRESHOLD = 0.6
# 无结构化结论时的回退：取 Markdown 首行（最多 N 字）作为占位结论
_FALLBACK_CHARS = 100


@dataclass
class SessionSummary:
    """一次会话的结构化摘要（供相关度召回与上下文注入）"""

    competitor: str = ""
    dimensions: list[str] = field(default_factory=list)
    key_conclusions: list[str] = field(default_factory=list)
    pending_gaps: list[str] = field(default_factory=list)
    created_at: str = ""
    session_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "competitor": self.competitor,
            "dimensions": self.dimensions,
            "key_conclusions": self.key_conclusions,
            "pending_gaps": self.pending_gaps,
            "created_at": self.created_at,
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionSummary":
        return cls(
            competitor=str(data.get("competitor", "")),
            dimensions=[str(d) for d in data.get("dimensions", []) if d],
            key_conclusions=[str(c) for c in data.get("key_conclusions", []) if c],
            pending_gaps=[str(g) for g in data.get("pending_gaps", []) if g],
            created_at=str(data.get("created_at", "")),
            session_id=str(data.get("session_id", "")),
        )


def summarize_session(session: dict[str, Any], max_conclusions: int = 5) -> SessionSummary:
    """从归档会话 dict 抽取结构化摘要（规则取高置信结论，无 LLM）。"""
    raw = session.get("raw") or {}
    if not isinstance(raw, dict):
        raw = {}
    competitor = str(session.get("competitor_name", "") or raw.get("competitor_name", ""))
    created_at = str(session.get("created_at", ""))
    session_id = str(session.get("session_id", ""))

    dimensions: list[str] = []
    conclusions: list[str] = []
    dims = raw.get("dimensions") or []
    if isinstance(dims, list):
        for item in dims:
            if not isinstance(item, dict):
                continue
            dimension = str(item.get("dimension", ""))
            if dimension and dimension not in dimensions:
                dimensions.append(dimension)
            summary = str(item.get("summary", "")).strip()
            try:
                conf = float(item.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            if summary and conf >= _CONFIDENCE_THRESHOLD:
                conclusions.append(f"{dimension}: {summary}" if dimension else summary)

    if not conclusions:
        # 回退：历史归档无结构化结论时取 Markdown 首行作占位（保证可检索）
        fallback = _markdown_lead(raw.get("markdown_report") or "")
        if fallback:
            conclusions.append(fallback)

    pending = [str(g) for g in (raw.get("pending_gaps") or []) if g]
    return SessionSummary(
        competitor=competitor,
        dimensions=dimensions,
        key_conclusions=conclusions[:max_conclusions],
        pending_gaps=pending,
        created_at=created_at,
        session_id=session_id,
    )


def compress_archive(
    entries: list[dict[str, Any]],
    keep_full: int = 5,
    summarize_rest: bool = True,
) -> list[dict[str, Any]]:
    """长存档滚动压缩：最近 keep_full 条保全文视图，更旧折叠为摘要条目。

    ``entries`` 需按 created_at 降序传入。返回上下文条目列表：
    - ``{"type": "session", session_id, created_at, summary}`` 最近会话（session_id 可回溯全文）；
    - ``{"type": "summary", ...}`` 折叠为摘要的旧会话；
    - ``summarize_rest=False`` 时更旧条目直接丢弃。
    """
    result: list[dict[str, Any]] = []
    for i, entry in enumerate(entries):
        if i < keep_full:
            kind = "session"
        elif summarize_rest:
            kind = "summary"
        else:
            continue
        result.append(
            {
                "type": kind,
                "session_id": str(entry.get("session_id", "")),
                "created_at": str(entry.get("created_at", "")),
                "summary": summarize_session(entry).to_dict(),
            }
        )
    return result


def _markdown_lead(markdown: str) -> str:
    """取 Markdown 首个非空行（去标题符）作为占位结论。"""
    for line in str(markdown).splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:_FALLBACK_CHARS]
    return ""
