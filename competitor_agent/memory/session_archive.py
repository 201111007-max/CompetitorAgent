"""L1 会话归档（SessionArchive）

按竞品归档每次分析会话，支持：
- 写读：archive() / retrieve()
- 去重：同一 session_id 重复归档只保留最新
- 老化：超过 ttl_days 的会话自动剔除（惰性清理）
- 摘要压缩：compress() 超限滚动压缩 + recent_context() 相关度召回（设计文档 35 §3.2）。
  压缩只影响内部注入路径（session_summaries），不改动 list_sessions/get_history 的全文契约。
"""
from __future__ import annotations

import logging
import math
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from competitor_agent.interfaces.context import AnalysisSession
from competitor_agent.knowledge_base.competitor_store import tokenize
from competitor_agent.memory.json_store import JsonStore, now_iso
from competitor_agent.memory.session_summary import compress_archive

logger = logging.getLogger("competitor_agent.memory.session_archive")


class SessionArchive:
    """L1 会话归档层（键 = competitor_name）"""

    def __init__(
        self,
        data_dir: Path | str | None = None,
        ttl_days: int = 30,
    ) -> None:
        self._store = JsonStore("session_archive", data_dir)
        # 压缩后的上下文视图（设计文档 35）：summary/session 条目，供 recent_context 召回
        self._summary_store = JsonStore("session_summaries", data_dir)
        self._max_entries = 20
        self._keep_full = 5
        self._ttl_days = ttl_days

    def archive(self, session: AnalysisSession) -> None:
        """归档一次会话；session_id 相同则覆盖（去重）"""
        if not session.competitor_name:
            raise ValueError("会话归档需要 competitor_name")
        sessions = self._sessions(session.competitor_name)
        payload = _session_to_dict(session)
        # 去重：同 session_id 覆盖
        replaced = False
        for i, item in enumerate(sessions):
            if item.get("session_id") == session.session_id:
                sessions[i] = payload
                replaced = True
                break
        if not replaced:
            sessions.append(payload)
        self._store.put(session.competitor_name, sessions)
        self._store.save()
        self._rebuild_context(session.competitor_name)
        logger.info("已归档会话 %s（%s）", session.session_id, session.competitor_name)

    def compress(self, max_entries: int = 20, keep_full: int = 5) -> None:
        """超限滚动压缩：为每个竞品重建上下文视图。

        最近 keep_full 条保全文视图，更旧折叠为摘要条目；每竞品最多保留 max_entries 条。
        """
        self._max_entries = max_entries
        self._keep_full = keep_full
        for competitor in self._store:
            self._rebuild_context(competitor)

    def recent_context(self, competitor: str, top_k: int = 5, query: str = "") -> list[str]:
        """按任务相关度召回可注入的记忆上下文（"摘要 + 最近相关会话"）。

        query 非空时经词袋相关度召回（复用 knowledge_base 的分词/余弦层，
        设计文档 32 向量层接入后由调用侧自动升级），否则取最近 top_k 条。
        返回可直接拼入 prompt 的文本行列表。
        """
        entries = self._summary_store.get(competitor, [])
        if not isinstance(entries, list) or not entries:
            return []
        if query:
            entries = _rank_entries(entries, query)
        return [_format_entry(e) for e in entries[:top_k]]

    def retrieve(self, competitor: str, limit: int = 20) -> list[AnalysisSession]:
        """取回某竞品最近会话（按 created_at 降序）"""
        sessions = self._sessions(competitor)
        sessions = self._age_out(sessions)
        if self._store.get(competitor, None) is not None:
            self._store.put(competitor, sessions)
            self._store.save()
        sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
        return [_session_from_dict(s) for s in sessions[:limit]]

    def recent_sessions(self) -> list[AnalysisSession]:
        """全部竞品的最近会话（按时间倒序）"""
        merged: list[dict[str, Any]] = []
        for competitor in self._store:
            merged.extend(self._sessions(competitor))
        merged.sort(key=lambda s: s.get("created_at", ""), reverse=True)
        return [_session_from_dict(s) for s in merged]

    def _sessions(self, competitor: str) -> list[dict[str, Any]]:
        raw = self._store.get(competitor, [])
        return raw if isinstance(raw, list) else []

    def _age_out(self, sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """剔除超过 TTL 的会话（惰性清理）"""
        cutoff = _cutoff_ts(self._ttl_days)
        kept: list[dict[str, Any]] = []
        for s in sessions:
            created = s.get("created_at", "")
            if not created:
                kept.append(s)
                continue
            ts = _parse_iso(created)
            if ts is None or ts >= cutoff:
                kept.append(s)
        return kept

    def _rebuild_context(self, competitor: str) -> None:
        """重建某竞品的压缩上下文视图（最近保全文、更旧折叠为摘要、封顶 max_entries）。"""
        sessions = self._age_out(self._sessions(competitor))
        sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
        context = compress_archive(sessions, keep_full=self._keep_full, summarize_rest=True)
        self._summary_store.put(competitor, context[: self._max_entries])
        self._summary_store.save()


def _rank_entries(entries: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """词袋相关度召回：按 query 与条目文本的 TF 余弦降序（复用 knowledge_base 分词层）。"""
    q_tokens = tokenize(query)
    if not q_tokens:
        return entries
    q_counts = Counter(q_tokens)
    q_norm = math.sqrt(sum(v * v for v in q_counts.values())) or 1.0
    scored: list[tuple[float, dict[str, Any]]] = []
    for entry in entries:
        e_counts = Counter(tokenize(_entry_text(entry)))
        dot = sum(v * e_counts.get(t, 0) for t, v in q_counts.items())
        e_norm = math.sqrt(sum(v * v for v in e_counts.values())) or 1.0
        scored.append((dot / (q_norm * e_norm), entry))
    scored.sort(key=lambda kv: kv[0], reverse=True)
    return [e for _, e in scored]


def _entry_text(entry: dict[str, Any]) -> str:
    """条目的可检索文本（竞品 + 维度 + 结论 + 遗留缺口）。"""
    s = entry.get("summary") or {}
    return " ".join(
        [
            str(s.get("competitor", "")),
            " ".join(str(d) for d in s.get("dimensions", [])),
            " ".join(str(c) for c in s.get("key_conclusions", [])),
            " ".join(str(g) for g in s.get("pending_gaps", [])),
        ]
    )


def _format_entry(entry: dict[str, Any]) -> str:
    """把一条上下文条目渲染为可注入 prompt 的文本（摘要视图，较全文精简）。"""
    s = entry.get("summary") or {}
    kind = "最近会话" if entry.get("type") == "session" else "历史摘要"
    created = str(s.get("created_at", ""))[:10]
    head = f"[{kind} {created}]".rstrip()
    conclusions = s.get("key_conclusions") or []
    lines = [head]
    if conclusions:
        lines.append("结论: " + "；".join(str(c) for c in conclusions))
    else:
        lines.append("（该会话无高置信结论）")
    pending = s.get("pending_gaps") or []
    if pending:
        lines.append("遗留缺口: " + ", ".join(str(g) for g in pending))
    return "\n".join(lines)


def _session_to_dict(session: AnalysisSession) -> dict[str, Any]:
    return {
        "task": session.task,
        "competitor_name": session.competitor_name,
        "session_id": session.session_id,
        "created_at": session.created_at or now_iso(),
        "raw": session.raw,
    }


def _session_from_dict(data: dict[str, Any]) -> AnalysisSession:
    return AnalysisSession(
        task=str(data.get("task", "")),
        competitor_name=str(data.get("competitor_name", "")),
        session_id=str(data.get("session_id", "")),
        created_at=str(data.get("created_at", "")),
        raw=data.get("raw", {}),
    )


def _parse_iso(value: str) -> float | None:
    """把 ISO 时间戳转 epoch 秒；解析失败返回 None"""
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _cutoff_ts(ttl_days: int) -> float:
    return time.time() - ttl_days * 86400