"""持久笔记模块 - Level 2 记忆层"""
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.memory.persistent_notes")


class PersistentNotes:
    """Level 2: 持久笔记（JSON + 索引）"""

    def __init__(self, json_path: str, max_entries: int = 100) -> None:
        self._json_path = Path(json_path)
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._notes: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        """从文件加载笔记"""
        if self._json_path.exists():
            try:
                with open(self._json_path, "r", encoding="utf-8") as f:
                    self._notes = json.load(f)
                logger.info(f"加载持久笔记: {len(self._notes)} 条")
            except Exception as e:
                logger.error(f"加载持久笔记失败: {e}")
                self._notes = []
        else:
            self._notes = []

    def _save(self) -> None:
        """保存笔记到文件"""
        self._json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._json_path, "w", encoding="utf-8") as f:
            json.dump(self._notes, f, ensure_ascii=False, indent=2)

    async def add_note(
        self,
        category: str,
        content: str,
        evidence: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """添加持久笔记"""
        # 使用单调递增 ID，避免删除后重复
        next_id = max([n["id"] for n in self._notes], default=0) + 1
        
        note = {
            "id": next_id,
            "category": category,
            "content": content,
            "evidence": evidence,
            "metadata": metadata or {},
            "created_at": datetime.now().isoformat(),
        }

        with self._lock:
            self._notes.append(note)
            self._cleanup_old_notes()
            self._save()

        logger.info(f"添加持久笔记: category={category}, id={note['id']}")

    def _cleanup_old_notes(self) -> None:
        """清理超出限制的旧笔记"""
        if len(self._notes) > self._max_entries:
            self._notes = self._notes[-self._max_entries:]

    async def query(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """检索持久笔记"""
        results = []
        query_lower = query.lower()

        for note in self._notes:
            if category and note["category"] != category:
                continue

            score = 0
            content_lower = note["content"].lower()

            if query_lower in content_lower:
                score += 2

            for keyword in query_lower.split():
                if keyword in content_lower:
                    score += 1

            for evidence in note["evidence"]:
                if query_lower in evidence.lower():
                    score += 1

            if score > 0:
                results.append({**note, "relevance_score": score})

        results.sort(key=lambda x: x["relevance_score"], reverse=True)
        return results[:top_k]

    async def get_by_category(self, category: str) -> List[Dict[str, Any]]:
        """按类别获取笔记"""
        return [note for note in self._notes if note["category"] == category]

    async def get_count(self) -> int:
        """获取笔记总数"""
        return len(self._notes)

    async def delete_note(self, note_id: int) -> bool:
        """删除指定笔记"""
        with self._lock:
            initial_count = len(self._notes)
            self._notes = [n for n in self._notes if n["id"] != note_id]
            if len(self._notes) < initial_count:
                self._save()
                logger.info(f"删除持久笔记: id={note_id}")
                return True
        return False
