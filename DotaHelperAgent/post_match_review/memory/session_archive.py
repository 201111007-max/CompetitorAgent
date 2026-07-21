"""会话归档模块 - Level 1 记忆层"""
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.memory.session_archive")


class SessionArchive:
    """Level 1: 会话归档（SQLite）"""

    def __init__(self, db_path: str, max_entries: int = 1000) -> None:
        self._db_path = Path(db_path)
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库表"""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_archive (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    quality_score REAL,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_match_id ON session_archive(match_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at ON session_archive(created_at)
            """)
            conn.commit()
        finally:
            conn.close()
        logger.info(f"SessionArchive 初始化完成: {self._db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        return sqlite3.connect(str(self._db_path))

    async def archive(
        self,
        match_id: str,
        report: Any,
        quality_score: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """归档复盘会话"""
        report_json = json.dumps(report, ensure_ascii=False, default=str)
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False, default=str)
        created_at = datetime.now().isoformat()

        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO session_archive
                    (match_id, report_json, quality_score, metadata_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (match_id, report_json, quality_score, metadata_json, created_at),
                )
                self._cleanup_old_entries(conn)

        logger.info(f"会话归档完成: match_id={match_id}, quality={quality_score}")

    def _cleanup_old_entries(self, conn: sqlite3.Connection) -> None:
        """清理超出限制的旧条目"""
        # 使用主键索引倒序查询，避免全表排序
        conn.execute("""
            DELETE FROM session_archive
            WHERE id NOT IN (
                SELECT id FROM session_archive
                ORDER BY id DESC
                LIMIT ?
            )
        """, (self._max_entries,))

    async def query_by_match_id(self, match_id: str) -> List[Dict[str, Any]]:
        """按比赛ID查询"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM session_archive WHERE match_id = ? ORDER BY created_at DESC",
                (match_id,),
            )
            rows = cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]

    async def query_by_time_range(
        self,
        start_time: str,
        end_time: str,
    ) -> List[Dict[str, Any]]:
        """按时间范围查询"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM session_archive
                WHERE created_at BETWEEN ? AND ?
                ORDER BY created_at DESC
                """,
                (start_time, end_time),
            )
            rows = cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]

    async def query_by_hero(self, hero_name: str) -> List[Dict[str, Any]]:
        """按英雄查询（从metadata中搜索）"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM session_archive
                WHERE metadata_json LIKE ?
                ORDER BY created_at DESC
                """,
                (f"%{hero_name}%",),
            )
            rows = cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        return {
            "id": row["id"],
            "match_id": row["match_id"],
            "report": json.loads(row["report_json"]),
            "quality_score": row["quality_score"],
            "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            "created_at": row["created_at"],
        }

    async def get_count(self) -> int:
        """获取归档总数"""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM session_archive")
            return cursor.fetchone()[0]
