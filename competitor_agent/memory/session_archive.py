"""L1 会话归档（SessionArchive）

按竞品归档每次分析会话，支持：
- 写读：archive() / retrieve()
- 去重：同一 session_id 重复归档只保留最新
- 老化：超过 ttl_days 的会话自动剔除（惰性清理）
- 摘要压缩：compress() 超限滚动压缩 + recent_context() 相关度召回（设计文档 35 §3.2）。
  压缩只影响内部注入路径（session_summaries），不改动 list_sessions/get_history 的全文契约。
- 向量召回（设计文档 52 §2.1）：可选注入 VectorStore（独立 collection），
  recent_context 向量优先，不可用/异常回退词袋（行为与现状逐位一致）。
"""
from __future__ import annotations

import logging
import math
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from competitor_agent.interfaces.context import AnalysisSession
from competitor_agent.knowledge_base.competitor_store import tokenize
from competitor_agent.memory.json_store import JsonStore, now_iso
from competitor_agent.memory.session_summary import compress_archive

if TYPE_CHECKING:
    from competitor_agent.knowledge_base.vector_store import VectorStore

logger = logging.getLogger("competitor_agent.memory.session_archive")


class SessionArchive:
    """L1 会话归档层（键 = competitor_name）"""

    def __init__(
        self,
        data_dir: Path | str | None = None,
        ttl_days: int = 30,
        vector_store: VectorStore | None = None,
    ) -> None:
        self._store = JsonStore("session_archive", data_dir)
        # 压缩后的上下文视图（设计文档 35）：summary/session 条目，供 recent_context 召回
        self._summary_store = JsonStore("session_summaries", data_dir)
        self._max_entries = 20
        self._keep_full = 5
        self._ttl_days = ttl_days
        # 向量层（设计文档 52）：可选注入；None/不可用 → 纯词袋召回（现状）
        self._vector_store = vector_store

    def attach_vector_store(self, vector_store: VectorStore) -> None:
        """构造后注入向量层（facade 在 enable_rag 时接入，设计文档 52 §3.1）。"""
        self._vector_store = vector_store

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

        query 非空时相关度召回：注入的向量层可用 → 语义召回（设计文档 52），
        不可用/集合为空/任何异常 → 回退词袋 TF 余弦（行为与现状逐位一致）；
        query 为空取最近 top_k 条。返回可直接拼入 prompt 的文本行列表。
        """
        if not competitor:
            # 品类级召回（设计文档 62 §3.9）：无具体竞品 → 跨竞品聚合摘要，按任务语义排序
            entries = self._category_entries()
        else:
            entries = self._summary_store.get(competitor, [])
        if not isinstance(entries, list) or not entries:
            return []
        if query:
            if competitor:
                ranked = self._vector_rank(entries, competitor, query)
                entries = ranked if ranked is not None else _rank_entries(entries, query)
            else:
                # 跨竞品条目无单一 competitor 键，向量按竞品过滤不可用 → 词袋排序（条目文本含竞品名）
                entries = _rank_entries(entries, query)
        return [_format_entry(e) for e in entries[:top_k]]

    def _category_entries(self) -> list[dict[str, Any]]:
        """聚合全部竞品的压缩上下文条目（品类级召回数据源）。"""
        merged: list[dict[str, Any]] = []
        for comp in self._store:
            comp_entries = self._summary_store.get(comp, [])
            if isinstance(comp_entries, list):
                merged.extend(comp_entries)
        return merged

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
        self._sync_vectors(competitor)

    def _sync_vectors(self, competitor: str) -> None:
        """向量同步（设计文档 52 §2.1）：增量 upsert 新条目 + 删除已老化/压缩剔除的条目。

        与 _rebuild_context 同事务调用；任何异常静默降级（记忆召回保持词袋路径）。
        老摘要经 get_existing 惰性 upsert，不做一次性强制回填。
        """
        vs = self._vector_store
        if vs is None:
            return
        try:
            if not vs.is_available():
                return
            entries = self._summary_store.get(competitor, [])
            entries = entries if isinstance(entries, list) else []
            ids = [_entry_id(competitor, e, i) for i, e in enumerate(entries)]
            existing = vs.get_existing(ids)
            new_ids = [eid for eid in ids if eid not in existing]
            if new_ids:
                texts = [_entry_text(entries[ids.index(eid)]) for eid in new_ids]
                vs.upsert(
                    new_ids,
                    vs.embed(texts),
                    [{"competitor": competitor}] * len(new_ids),
                )
            stale = vs.list_ids(where={"competitor": competitor}) - set(ids)
            if stale:
                vs.delete(sorted(stale))
        except Exception:
            logger.debug("记忆向量同步失败（%s），保持词袋召回", competitor, exc_info=True)

    def _vector_rank(
        self, entries: list[dict[str, Any]], competitor: str, query: str
    ) -> list[dict[str, Any]] | None:
        """向量语义召回：按 L2 距离升序返回条目；不可用/空集/异常 → None（回退词袋）。

        向量集合未覆盖的条目（如刚注入尚未同步的老摘要）按原序追加兜底，
        保证召回条数不缩水。
        """
        vs = self._vector_store
        if vs is None:
            return None
        try:
            if not vs.is_available():
                return None
            query_vec = vs.embed([query])[0]
            hits = vs.search(query_vec, top_k=len(entries), where={"competitor": competitor})
            if not hits:
                return None
            by_id = {_entry_id(competitor, e, i): e for i, e in enumerate(entries)}
            ranked: list[dict[str, Any]] = []
            seen: set[str] = set()
            for eid, _dist in hits:
                entry = by_id.get(eid)
                if entry is not None and eid not in seen:
                    seen.add(eid)
                    ranked.append(entry)
            for i, entry in enumerate(entries):
                eid = _entry_id(competitor, entry, i)
                if eid not in seen:
                    ranked.append(entry)
            return ranked
        except Exception:
            logger.debug("记忆向量召回失败，回退词袋", exc_info=True)
            return None


def _entry_id(competitor: str, entry: dict[str, Any], index: int) -> str:
    """向量条目 id（设计文档 52 §2.1）：{competitor}:{session_id 或摘要索引}。

    同 session_id 重复归档 → 同 id upsert 覆盖（幂等）；无 session_id 的条目
    用索引兜底（视图按 created_at 降序，索引稳定）。
    """
    sid = str(entry.get("session_id", "") or f"idx{index}")
    return f"{competitor}:{sid}"


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