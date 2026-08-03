"""L1 会话归档（SessionArchive）

按竞品归档每次分析会话，支持：
- 写读：archive() / retrieve()
- 去重：同一 session_id 重复归档只保留最新
- 老化：超过 ttl_days 的会话自动剔除（惰性清理）
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from competitor_agent.interfaces.context import AnalysisSession
from competitor_agent.memory.json_store import JsonStore, now_iso

logger = logging.getLogger("competitor_agent.memory.session_archive")


class SessionArchive:
    """L1 会话归档层（键 = competitor_name）"""

    def __init__(
        self,
        data_dir: Path | str | None = None,
        ttl_days: int = 30,
    ) -> None:
        self._store = JsonStore("session_archive", data_dir)
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
        logger.info("已归档会话 %s（%s）", session.session_id, session.competitor_name)

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