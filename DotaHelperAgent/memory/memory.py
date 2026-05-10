"""Agent 记忆系统 - 支持短期、长期和情景记忆"""

import threading
import time
import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
import pickle


class MemoryType(Enum):
    """记忆类型枚举"""
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    EPISODIC = "episodic"


@dataclass
class MemoryEntry:
    """记忆条目"""
    key: str
    value: Any
    memory_type: MemoryType
    timestamp: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)
    access_count: int = 0
    last_access: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "memory_type": self.memory_type.value,
            "timestamp": self.timestamp,
            "tags": self.tags,
            "access_count": self.access_count,
            "last_access": self.last_access
        }


@dataclass
class EpisodicEntry:
    """情景记忆条目 - 记录事件"""
    event_type: str
    content: Any
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    sentiment: Optional[str] = None
    outcome: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "content": self.content,
            "context": self.context,
            "timestamp": self.timestamp,
            "sentiment": self.sentiment,
            "outcome": self.outcome
        }


class AgentMemory:
    """Agent 记忆系统

    特性：
    - 短期记忆：当前会话期间的信息
    - 长期记忆：持久化存储的用户偏好和知识
    - 情景记忆：历史事件和经验记录
    - 线程安全
    - 自动过期机制
    - 相关上下文检索
    """

    def __init__(
        self,
        memory_dir: str = "memory",
        short_term_ttl: int = 3600,
        long_term_max_items: int = 1000,
        episodic_max_entries: int = 500
    ):
        """初始化记忆系统

        Args:
            memory_dir: 记忆存储目录
            short_term_ttl: 短期记忆 TTL（秒），默认 1 小时
            long_term_max_items: 长期记忆最大条目数
            episodic_max_entries: 情景记忆最大条目数
        """
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(exist_ok=True)
        self.short_term_ttl = short_term_ttl
        self.long_term_max_items = long_term_max_items
        self.episodic_max_entries = episodic_max_entries

        self._lock = threading.RLock()

        self._short_term: Dict[str, MemoryEntry] = {}
        self._long_term_db = self.memory_dir / "long_term.db"
        self._episodic_db = self.memory_dir / "episodic.db"

        self._init_databases()

    def _init_databases(self) -> None:
        """初始化 SQLite 数据库"""
        with self._lock:
            conn = sqlite3.connect(str(self._long_term_db))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS long_term_memory (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    tags TEXT,
                    access_count INTEGER DEFAULT 0,
                    last_access REAL
                )
            """)
            conn.commit()
            conn.close()

            conn = sqlite3.connect(str(self._episodic_db))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodic_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    context TEXT,
                    timestamp REAL NOT NULL,
                    sentiment TEXT,
                    outcome TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON episodic_memory(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_type ON episodic_memory(event_type)")
            conn.commit()
            conn.close()

    def remember(
        self,
        key: str,
        value: Any,
        memory_type: str = "short",
        tags: Optional[List[str]] = None
    ) -> bool:
        """记住信息

        Args:
            key: 记忆键
            value: 记忆值
            memory_type: 记忆类型 ("short", "long", "episodic")
            tags: 标签列表

        Returns:
            bool: 是否成功
        """
        with self._lock:
            mem_type = MemoryType.SHORT_TERM if memory_type == "short" else MemoryType.LONG_TERM

            if mem_type == MemoryType.SHORT_TERM:
                return self._remember_short_term(key, value, tags)
            else:
                return self._remember_long_term(key, value, tags)

    def _remember_short_term(
        self,
        key: str,
        value: Any,
        tags: Optional[List[str]] = None
    ) -> bool:
        """存储短期记忆"""
        entry = MemoryEntry(
            key=key,
            value=value,
            memory_type=MemoryType.SHORT_TERM,
            tags=tags or []
        )
        self._short_term[key] = entry
        return True

    def _remember_long_term(
        self,
        key: str,
        value: Any,
        tags: Optional[List[str]] = None
    ) -> bool:
        """存储长期记忆"""
        try:
            serialized_value = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
            conn = sqlite3.connect(str(self._long_term_db))
            conn.execute("""
                INSERT OR REPLACE INTO long_term_memory (key, value, timestamp, tags, access_count, last_access)
                VALUES (?, ?, ?, ?, COALESCE((SELECT access_count FROM long_term_memory WHERE key = ?), 0), ?)
            """, (key, serialized_value, time.time(), json.dumps(tags or []), key, time.time()))
            conn.commit()
            conn.close()
            self._evict_long_term_if_needed()
            return True
        except Exception:
            return False

    def recall(
        self,
        key: str,
        memory_type: str = "short",
        default: Any = None
    ) -> Any:
        """回忆信息

        Args:
            key: 记忆键
            memory_type: 记忆类型 ("short", "long", "episodic")
            default: 默认值

        Returns:
            Any: 记忆值
        """
        with self._lock:
            mem_type = MemoryType.SHORT_TERM if memory_type == "short" else MemoryType.LONG_TERM

            if mem_type == MemoryType.SHORT_TERM:
                return self._recall_short_term(key, default)
            else:
                return self._recall_long_term(key, default)

    def _recall_short_term(self, key: str, default: Any) -> Any:
        """检索短期记忆"""
        entry = self._short_term.get(key)
        if entry is None:
            return default

        if time.time() - entry.timestamp > self.short_term_ttl:
            del self._short_term[key]
            return default

        entry.access_count += 1
        entry.last_access = time.time()
        return entry.value

    def _recall_long_term(self, key: str, default: Any) -> Any:
        """检索长期记忆"""
        try:
            conn = sqlite3.connect(str(self._long_term_db))
            cursor = conn.execute("""
                SELECT value, access_count FROM long_term_memory WHERE key = ?
            """, (key,))
            row = cursor.fetchone()
            conn.close()

            if row is None:
                return default

            value_str, access_count = row
            try:
                value = json.loads(value_str)
            except json.JSONDecodeError:
                value = value_str

            conn = sqlite3.connect(str(self._long_term_db))
            conn.execute("UPDATE long_term_memory SET access_count = ?, last_access = ? WHERE key = ?",
                        (access_count + 1, time.time(), key))
            conn.commit()
            conn.close()

            return value
        except Exception:
            return default

    def record_episode(
        self,
        event_type: str,
        content: Any,
        context: Optional[Dict[str, Any]] = None,
        sentiment: Optional[str] = None,
        outcome: Optional[str] = None
    ) -> bool:
        """记录情景记忆

        Args:
            event_type: 事件类型
            content: 事件内容
            context: 上下文信息
            sentiment: 情感倾向
            outcome: 结果

        Returns:
            bool: 是否成功
        """
        try:
            serialized_content = json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content
            serialized_context = json.dumps(context or {}, ensure_ascii=False)

            conn = sqlite3.connect(str(self._episodic_db))
            conn.execute("""
                INSERT INTO episodic_memory (event_type, content, context, timestamp, sentiment, outcome)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (event_type, serialized_content, serialized_context, time.time(), sentiment, outcome))
            conn.commit()
            conn.close()

            self._evict_episodic_if_needed()
            return True
        except Exception:
            return False

    def get_recent_episodes(
        self,
        event_type: Optional[str] = None,
        limit: int = 10
    ) -> List[EpisodicEntry]:
        """获取最近的情景记忆

        Args:
            event_type: 事件类型过滤
            limit: 返回数量

        Returns:
            List[EpisodicEntry]: 情景记忆列表
        """
        try:
            conn = sqlite3.connect(str(self._episodic_db))

            if event_type:
                cursor = conn.execute("""
                    SELECT event_type, content, context, timestamp, sentiment, outcome
                    FROM episodic_memory
                    WHERE event_type = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (event_type, limit))
            else:
                cursor = conn.execute("""
                    SELECT event_type, content, context, timestamp, sentiment, outcome
                    FROM episodic_memory
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))

            rows = cursor.fetchall()
            conn.close()

            episodes = []
            for row in rows:
                try:
                    content = json.loads(row[1])
                except json.JSONDecodeError:
                    content = row[1]
                try:
                    context = json.loads(row[2])
                except json.JSONDecodeError:
                    context = {}

                episodes.append(EpisodicEntry(
                    event_type=row[0],
                    content=content,
                    context=context,
                    timestamp=row[3],
                    sentiment=row[4],
                    outcome=row[5]
                ))
            return episodes
        except Exception:
            return []

    def get_relevant_context(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """获取与查询相关的上下文

        Args:
            query: 查询关键词
            limit: 返回数量

        Returns:
            List[Dict[str, Any]]: 相关上下文列表
        """
        context = []

        with self._lock:
            for entry in self._short_term.values():
                if query.lower() in str(entry.value).lower() or query.lower() in entry.key.lower():
                    context.append({
                        "type": "short_term",
                        "key": entry.key,
                        "value": entry.value,
                        "timestamp": entry.timestamp,
                        "relevance_score": self._calculate_relevance(entry, query)
                    })

        try:
            conn = sqlite3.connect(str(self._long_term_db))
            cursor = conn.execute("""
                SELECT key, value, timestamp FROM long_term_memory
            """)
            for row in cursor:
                if query.lower() in row[1].lower() or query.lower() in row[0].lower():
                    try:
                        value = json.loads(row[1])
                    except json.JSONDecodeError:
                        value = row[1]
                    context.append({
                        "type": "long_term",
                        "key": row[0],
                        "value": value,
                        "timestamp": row[2],
                        "relevance_score": 1.0
                    })
            conn.close()
        except Exception:
            pass

        context.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        return context[:limit]

    def _calculate_relevance(self, entry: MemoryEntry, query: str) -> float:
        """计算记忆条目与查询的相关性"""
        score = 0.0

        if query.lower() in entry.key.lower():
            score += 2.0

        if query.lower() in str(entry.value).lower():
            score += 1.0

        for tag in entry.tags:
            if query.lower() in tag.lower():
                score += 0.5

        if entry.access_count > 0:
            score += min(entry.access_count * 0.1, 1.0)

        return score

    def _evict_long_term_if_needed(self) -> None:
        """如果长期记忆超过最大条目数，执行 LRU 淘汰"""
        try:
            conn = sqlite3.connect(str(self._long_term_db))
            cursor = conn.execute("SELECT COUNT(*) FROM long_term_memory")
            count = cursor.fetchone()[0]

            if count > self.long_term_max_items:
                conn.execute("""
                    DELETE FROM long_term_memory
                    WHERE key IN (
                        SELECT key FROM long_term_memory
                        ORDER BY last_access ASC
                        LIMIT ?
                    )
                """, (count - self.long_term_max_items,))
                conn.commit()
            conn.close()
        except Exception:
            pass

    def _evict_episodic_if_needed(self) -> None:
        """如果情景记忆超过最大条目数，删除最旧的条目"""
        try:
            conn = sqlite3.connect(str(self._episodic_db))
            cursor = conn.execute("SELECT COUNT(*) FROM episodic_memory")
            count = cursor.fetchone()[0]

            if count > self.episodic_max_entries:
                conn.execute("""
                    DELETE FROM episodic_memory
                    WHERE id IN (
                        SELECT id FROM episodic_memory
                        ORDER BY timestamp ASC
                        LIMIT ?
                    )
                """, (count - self.episodic_max_entries,))
                conn.commit()
            conn.close()
        except Exception:
            pass

    def clear_short_term(self) -> bool:
        """清空短期记忆"""
        with self._lock:
            self._short_term.clear()
            return True

    def clear_all(self) -> bool:
        """清空所有记忆"""
        with self._lock:
            self._short_term.clear()
            try:
                conn = sqlite3.connect(str(self._long_term_db))
                conn.execute("DELETE FROM long_term_memory")
                conn.commit()
                conn.close()

                conn = sqlite3.connect(str(self._episodic_db))
                conn.execute("DELETE FROM episodic_memory")
                conn.commit()
                conn.close()
            except Exception:
                return False
            return True

    def get_stats(self) -> Dict[str, Any]:
        """获取记忆系统统计信息"""
        stats = {
            "short_term_count": len(self._short_term),
            "long_term_count": 0,
            "episodic_count": 0
        }

        try:
            conn = sqlite3.connect(str(self._long_term_db))
            cursor = conn.execute("SELECT COUNT(*) FROM long_term_memory")
            stats["long_term_count"] = cursor.fetchone()[0]
            conn.close()

            conn = sqlite3.connect(str(self._episodic_db))
            cursor = conn.execute("SELECT COUNT(*) FROM episodic_memory")
            stats["episodic_count"] = cursor.fetchone()[0]
            conn.close()
        except Exception:
            pass

        return stats