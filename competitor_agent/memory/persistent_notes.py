"""L2 持久笔记（PersistentNotes）

按竞品保存分析过程产生的笔记/结论片段，支持：
- 写读：save_note() / retrieve_notes()
- 去重：相同内容不重复写入
- 上限：每个竞品保留最近 N 条（先进先出裁剪）
"""
from __future__ import annotations

import logging
from pathlib import Path

from competitor_agent.memory.json_store import JsonStore, now_iso

logger = logging.getLogger("competitor_agent.memory.persistent_notes")

_MAX_NOTES_PER_COMPETITOR = 200


class PersistentNotes:
    """L2 持久笔记层（键 = competitor_name）"""

    def __init__(
        self,
        data_dir: Path | str | None = None,
        max_per_competitor: int = _MAX_NOTES_PER_COMPETITOR,
    ) -> None:
        self._store = JsonStore("persistent_notes", data_dir)
        self._max_per_competitor = max_per_competitor

    def save_note(self, competitor: str, note: str) -> None:
        """保存一条笔记；内容去重 + 裁剪到上限"""
        note = note.strip()
        if not note:
            return
        notes = self._notes(competitor)
        # 去重：已存在相同内容则更新其时间戳（避免重复）
        for item in notes:
            if item["text"] == note:
                item["created_at"] = now_iso()
                self._persist(competitor, notes)
                return
        notes.append({"text": note, "created_at": now_iso()})
        # 裁剪：保留最近 max 条
        if len(notes) > self._max_per_competitor:
            notes = notes[-self._max_per_competitor:]
        self._persist(competitor, notes)

    def retrieve_notes(self, competitor: str) -> list[str]:
        """取回某竞品笔记（按时间倒序）"""
        notes = self._notes(competitor)
        notes.sort(key=lambda n: n.get("created_at", ""), reverse=True)
        return [n["text"] for n in notes]

    def all_notes(self) -> dict[str, list[str]]:
        """全部竞品的笔记摘要"""
        return {c: [n["text"] for n in self._notes(c)] for c in self._store}

    def _notes(self, competitor: str) -> list[dict[str, str]]:
        raw = self._store.get(competitor, [])
        return raw if isinstance(raw, list) else []

    def _persist(self, competitor: str, notes: list[dict[str, str]]) -> None:
        self._store.put(competitor, notes)
        self._store.save()