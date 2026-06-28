"""
反馈存储层 - 持久化存储反馈记录

职责：
- 存储反馈记录到 SQLite
- 提供查询和聚合接口
- 支持按引擎、规则、场景维度查询
- 自动清理过期数据
"""

import sqlite3
import json
import time
import uuid
import threading
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class FeedbackRecord:
    """反馈记录"""
    feedback_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    recommendation_id: str = ""
    feedback_type: str = ""  # "explicit" | "implicit"
    score: float = 0.0
    engine: str = ""  # "rule" | "data" | "llm"
    event_type: str = ""
    rule_name: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "feedback_id": self.feedback_id,
            "recommendation_id": self.recommendation_id,
            "feedback_type": self.feedback_type,
            "score": self.score,
            "engine": self.engine,
            "event_type": self.event_type,
            "rule_name": self.rule_name,
            "context": self.context,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class AggregateStats:
    """聚合统计"""
    count: int = 0
    avg_score: float = 0.0
    positive_rate: float = 0.0
    std_score: float = 0.0
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "count": self.count,
            "avg_score": self.avg_score,
            "positive_rate": self.positive_rate,
            "std_score": self.std_score,
            "last_updated": self.last_updated,
        }


class FeedbackStore:
    """反馈存储"""

    def __init__(self, db_path: str = "feedback/feedback.db"):
        """
        初始化反馈存储

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = Path(db_path)
        if not self.db_path.is_absolute():
            self.db_path = Path(__file__).parent.parent / db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._init_database()
        logger.info(f"反馈存储初始化完成: {self.db_path}")

    def _init_database(self) -> None:
        """初始化数据库表"""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback_records (
                    feedback_id TEXT PRIMARY KEY,
                    recommendation_id TEXT NOT NULL,
                    feedback_type TEXT NOT NULL,
                    score REAL NOT NULL,
                    engine TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    rule_name TEXT,
                    context TEXT,
                    timestamp REAL NOT NULL,
                    metadata TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_engine ON feedback_records(engine)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_type ON feedback_records(event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON feedback_records(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_recommendation_id ON feedback_records(recommendation_id)")
            conn.commit()
            conn.close()

    def save(self, record: FeedbackRecord) -> None:
        """
        保存反馈记录

        Args:
            record: 反馈记录
        """
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("""
                INSERT OR REPLACE INTO feedback_records
                (feedback_id, recommendation_id, feedback_type, score, engine,
                 event_type, rule_name, context, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.feedback_id,
                record.recommendation_id,
                record.feedback_type,
                record.score,
                record.engine,
                record.event_type,
                record.rule_name,
                json.dumps(record.context, ensure_ascii=False),
                record.timestamp,
                json.dumps(record.metadata, ensure_ascii=False),
            ))
            conn.commit()
            conn.close()
        logger.debug(f"保存反馈记录: {record.feedback_id}")

    def get_by_engine(self, engine: str, since: Optional[float] = None) -> List[FeedbackRecord]:
        """
        按引擎查询反馈

        Args:
            engine: 引擎名称
            since: 起始时间戳

        Returns:
            反馈记录列表
        """
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            if since:
                cursor = conn.execute("""
                    SELECT * FROM feedback_records
                    WHERE engine = ? AND timestamp >= ?
                    ORDER BY timestamp DESC
                """, (engine, since))
            else:
                cursor = conn.execute("""
                    SELECT * FROM feedback_records
                    WHERE engine = ?
                    ORDER BY timestamp DESC
                """, (engine,))

            records = [self._row_to_record(row) for row in cursor.fetchall()]
            conn.close()
            return records

    def get_by_rule(self, rule_name: str, since: Optional[float] = None) -> List[FeedbackRecord]:
        """
        按规则查询反馈

        Args:
            rule_name: 规则名称
            since: 起始时间戳

        Returns:
            反馈记录列表
        """
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            if since:
                cursor = conn.execute("""
                    SELECT * FROM feedback_records
                    WHERE rule_name = ? AND timestamp >= ?
                    ORDER BY timestamp DESC
                """, (rule_name, since))
            else:
                cursor = conn.execute("""
                    SELECT * FROM feedback_records
                    WHERE rule_name = ?
                    ORDER BY timestamp DESC
                """, (rule_name,))

            records = [self._row_to_record(row) for row in cursor.fetchall()]
            conn.close()
            return records

    def get_by_event_type(self, event_type: str, since: Optional[float] = None) -> List[FeedbackRecord]:
        """
        按事件类型查询反馈

        Args:
            event_type: 事件类型
            since: 起始时间戳

        Returns:
            反馈记录列表
        """
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            if since:
                cursor = conn.execute("""
                    SELECT * FROM feedback_records
                    WHERE event_type = ? AND timestamp >= ?
                    ORDER BY timestamp DESC
                """, (event_type, since))
            else:
                cursor = conn.execute("""
                    SELECT * FROM feedback_records
                    WHERE event_type = ?
                    ORDER BY timestamp DESC
                """, (event_type,))

            records = [self._row_to_record(row) for row in cursor.fetchall()]
            conn.close()
            return records

    def get_aggregate(self, group_by: str, since: Optional[float] = None) -> Dict[str, AggregateStats]:
        """
        聚合查询

        Args:
            group_by: 分组字段 ("engine" | "rule_name" | "event_type")
            since: 起始时间戳

        Returns:
            聚合统计字典
        """
        if group_by not in ["engine", "rule_name", "event_type"]:
            logger.warning(f"不支持的分组字段: {group_by}")
            return {}

        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            if since:
                cursor = conn.execute(f"""
                    SELECT {group_by}, COUNT(*), AVG(score),
                           SUM(CASE WHEN score > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*),
                           MAX(timestamp)
                    FROM feedback_records
                    WHERE timestamp >= ? AND {group_by} IS NOT NULL
                    GROUP BY {group_by}
                """, (since,))
            else:
                cursor = conn.execute(f"""
                    SELECT {group_by}, COUNT(*), AVG(score),
                           SUM(CASE WHEN score > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*),
                           MAX(timestamp)
                    FROM feedback_records
                    WHERE {group_by} IS NOT NULL
                    GROUP BY {group_by}
                """)

            result = {}
            for row in cursor.fetchall():
                key = row[0]
                stats = AggregateStats(
                    count=row[1],
                    avg_score=row[2] if row[2] else 0.0,
                    positive_rate=row[3] if row[3] else 0.0,
                    std_score=0.0,  # SQLite 不支持 STDDEV，后续可计算
                    last_updated=row[4] if row[4] else time.time(),
                )
                result[key] = stats

            conn.close()
            return result

    def cleanup(self, max_age_days: int = 30) -> int:
        """
        清理过期数据

        Args:
            max_age_days: 最大保留天数

        Returns:
            删除的记录数
        """
        cutoff_time = time.time() - (max_age_days * 86400)
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.execute("""
                DELETE FROM feedback_records WHERE timestamp < ?
            """, (cutoff_time,))
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()

        if deleted_count > 0:
            logger.info(f"清理过期反馈记录: {deleted_count} 条")
        return deleted_count

    def _row_to_record(self, row: tuple) -> FeedbackRecord:
        """
        将数据库行转换为 FeedbackRecord

        Args:
            row: 数据库行

        Returns:
            FeedbackRecord 对象
        """
        return FeedbackRecord(
            feedback_id=row[0],
            recommendation_id=row[1],
            feedback_type=row[2],
            score=row[3],
            engine=row[4],
            event_type=row[5],
            rule_name=row[6],
            context=json.loads(row[7]) if row[7] else {},
            timestamp=row[8],
            metadata=json.loads(row[9]) if row[9] else {},
        )
