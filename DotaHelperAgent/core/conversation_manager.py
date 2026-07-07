"""会话管理器 - 多轮对话上下文管理

实现完整的会话生命周期管理、对话历史维护、上下文压缩和实体追踪
"""

import sqlite3
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum

from utils.log_config import get_logger
from utils.trace_context import get_current_trace

logger = get_logger("conversation_manager", component="core")


class MessageRole(Enum):
    """消息角色枚举"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass
class Message:
    """单条对话消息"""
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=data.get("timestamp", time.time()),
            metadata=data.get("metadata", {})
        )


@dataclass
class ConversationSession:
    """对话会话"""
    session_id: str
    messages: List[Message] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    turn_count: int = 0

    context_state: Dict[str, Any] = field(default_factory=dict)
    entity_history: Dict[str, List[Dict]] = field(default_factory=dict)
    last_compressed_turn: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "messages": [msg.to_dict() for msg in self.messages],
            "created_at": self.created_at,
            "last_active": self.last_active,
            "turn_count": self.turn_count,
            "context_state": self.context_state,
            "entity_history": self.entity_history,
            "last_compressed_turn": self.last_compressed_turn
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationSession":
        session = cls(
            session_id=data["session_id"],
            created_at=data.get("created_at", time.time()),
            last_active=data.get("last_active", time.time()),
            turn_count=data.get("turn_count", 0),
            context_state=data.get("context_state", {}),
            entity_history=data.get("entity_history", {}),
            last_compressed_turn=data.get("last_compressed_turn", 0)
        )
        session.messages = [Message.from_dict(msg) for msg in data.get("messages", [])]
        return session

    def add_message(self, message: Message) -> None:
        """添加消息"""
        self.messages.append(message)
        self.last_active = time.time()
        if message.role == MessageRole.USER.value:
            self.turn_count += 1

    def get_recent_messages(self, limit: int = 10) -> List[Message]:
        """获取最近的消息"""
        return self.messages[-limit:] if len(self.messages) > limit else self.messages

    def update_context_state(self, key: str, value: Any) -> None:
        """更新上下文状态"""
        self.context_state[key] = value
        self.last_active = time.time()

    def track_entity(self, entity_type: str, entity_data: Dict[str, Any]) -> None:
        """追踪实体"""
        if entity_type not in self.entity_history:
            self.entity_history[entity_type] = []
        self.entity_history[entity_type].append({
            **entity_data,
            "timestamp": time.time()
        })

    def get_current_heroes(self) -> Dict[str, List[str]]:
        """获取当前讨论的英雄"""
        return self.context_state.get("current_heroes", {"our": [], "enemy": []})

    def get_current_topic(self) -> str:
        """获取当前话题"""
        return self.context_state.get("current_topic", "general")


class ConversationManager:
    """会话管理器

    特性：
    - 会话生命周期管理
    - 对话历史维护
    - 上下文压缩
    - 实体追踪
    - SQLite 持久化
    - 自动过期清理
    """

    MAX_TURNS = 20
    MAX_CONTEXT_TURNS = 5
    SESSION_TTL = 1800

    def __init__(
        self,
        storage_dir: str = "memory",
        session_ttl: int = 1800,
        max_turns: int = 20,
        max_context_turns: int = 5,
        llm_client: Optional[Any] = None,
        async_compress: bool = False
    ):
        """初始化会话管理器

        Args:
            storage_dir: 存储目录
            session_ttl: 会话过期时间（秒）
            max_turns: 最大对话轮数
            max_context_turns: 保留完整上下文的轮数
            llm_client: LLM 客户端（可选，用于生成高质量摘要）
            async_compress: 是否异步执行压缩（避免阻塞主流程）
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)
        self.session_ttl = session_ttl
        self.max_turns = max_turns
        self.max_context_turns = max_context_turns
        self.llm_client = llm_client
        self.async_compress = async_compress

        self._lock = threading.RLock()
        self._active_sessions: Dict[str, ConversationSession] = {}

        # 异步压缩线程池（仅在有 LLM 客户端且开启异步时创建）
        self._compress_executor: Optional[ThreadPoolExecutor] = None
        if async_compress and llm_client:
            self._compress_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="compress")

        self._db_path = self.storage_dir / "conversations.db"
        self._init_database()

    def _init_database(self) -> None:
        """初始化 SQLite 数据库"""
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_active REAL NOT NULL,
                    turn_count INTEGER DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_last_active ON sessions(last_active)")
            conn.commit()
            conn.close()

    def create_session(self, session_id: str) -> ConversationSession:
        """创建新会话

        Args:
            session_id: 会话 ID

        Returns:
            ConversationSession: 新创建的会话
        """
        with self._lock:
            session = ConversationSession(session_id=session_id)
            self._active_sessions[session_id] = session
            self._save_session_to_db(session)
            return session

    def get_session(self, session_id: str) -> Optional[ConversationSession]:
        """获取会话

        Args:
            session_id: 会话 ID

        Returns:
            ConversationSession 或 None
        """
        with self._lock:
            if session_id in self._active_sessions:
                session = self._active_sessions[session_id]
                if not self._is_session_expired(session):
                    return session
                else:
                    del self._active_sessions[session_id]

            session = self._load_session_from_db(session_id)
            if session and not self._is_session_expired(session):
                self._active_sessions[session_id] = session
                return session

            return None

    def get_or_create_session(self, session_id: str) -> ConversationSession:
        """获取或创建会话

        Args:
            session_id: 会话 ID

        Returns:
            ConversationSession: 会话实例
        """
        session = self.get_session(session_id)
        if session is None:
            session = self.create_session(session_id)
        return session

    def add_message(self, session_id: str, message: Message) -> bool:
        """添加消息到会话

        Args:
            session_id: 会话 ID
            message: 消息对象

        Returns:
            bool: 是否成功
        """
        with self._lock:
            session = self.get_session(session_id)
            if session is None:
                return False

            # 检查是否需要压缩：距离上次压缩后又超过 max_turns 轮
            turns_since_compress = session.turn_count - session.last_compressed_turn
            if turns_since_compress >= self.max_turns:
                self._compress_session(session)

            session.add_message(message)

            if message.role == MessageRole.USER.value:
                entities = message.metadata.get("entities", [])
                for entity in entities:
                    session.track_entity(entity.get("type", "unknown"), entity)

            self._save_session_to_db(session)
            return True

    def get_history(self, session_id: str, limit: int = 10) -> List[Message]:
        """获取对话历史

        Args:
            session_id: 会话 ID
            limit: 返回数量

        Returns:
            List[Message]: 消息列表
        """
        session = self.get_session(session_id)
        if session is None:
            return []

        return session.get_recent_messages(limit)

    def get_context(self, session_id: str) -> Dict[str, Any]:
        """获取会话上下文

        Args:
            session_id: 会话 ID

        Returns:
            Dict: 上下文信息
        """
        session = self.get_session(session_id)
        if session is None:
            return {}

        return {
            "conversation_history": [msg.to_dict() for msg in session.get_recent_messages(self.max_context_turns * 2)],
            "current_heroes": session.get_current_heroes(),
            "current_topic": session.get_current_topic(),
            "turn_count": session.turn_count,
            "entity_history": session.entity_history
        }

    def update_context_state(self, session_id: str, key: str, value: Any) -> bool:
        """更新上下文状态

        Args:
            session_id: 会话 ID
            key: 状态键
            value: 状态值

        Returns:
            bool: 是否成功
        """
        with self._lock:
            session = self.get_session(session_id)
            if session is None:
                return False

            session.update_context_state(key, value)
            self._save_session_to_db(session)
            return True

    def compress_context(self, session_id: str) -> Optional[str]:
        """压缩会话上下文（分层压缩策略）

        分层策略：
        - 最近 5 轮：完整保留（不压缩）
        - 5-20 轮：轻量摘要（关键实体+结论）
        - 20+ 轮：深度摘要（仅保留核心决策）

        Args:
            session_id: 会话 ID

        Returns:
            str 或 None: 压缩后的摘要
        """
        session = self.get_session(session_id)
        if session is None:
            return None

        # 分层压缩逻辑
        if session.turn_count <= self.max_context_turns:
            # 最近 5 轮：完整保留
            return self._format_full_history(session.messages)
        
        # 计算距离上次压缩的轮次
        turns_since_compress = session.turn_count - session.last_compressed_turn
        
        if turns_since_compress < 20:
            # 5-20 轮：轻量压缩（保留最近 10 条消息）
            keep_count = self.max_context_turns * 2  # 10 条
            compression_level = "light"
        else:
            # 20+ 轮：深度压缩（保留最近 6 条消息）
            keep_count = 6
            compression_level = "deep"
        
        if len(session.messages) <= keep_count:
            return None
        
        old_messages = session.messages[:-keep_count]
        recent_messages = session.messages[-keep_count:]
        
        # 根据压缩级别生成不同详细程度的摘要
        summary = self._generate_summary(old_messages, level=compression_level)
        
        # 构建压缩后的消息列表
        level_label = "轻量摘要" if compression_level == "light" else "深度摘要"
        session.messages = [
            Message(
                role=MessageRole.SYSTEM.value,
                content=f"[{level_label}] {summary}",
                timestamp=session.created_at
            )
        ] + recent_messages
        
        # 记录压缩时的轮次，避免重复压缩
        session.last_compressed_turn = session.turn_count
        
        self._save_session_to_db(session)
        return summary

    def is_session_expired(self, session_id: str) -> bool:
        """检查会话是否过期

        Args:
            session_id: 会话 ID

        Returns:
            bool: 是否过期
        """
        session = self.get_session(session_id)
        if session is None:
            return True
        return self._is_session_expired(session)

    def close_session(self, session_id: str) -> bool:
        """关闭会话

        Args:
            session_id: 会话 ID

        Returns:
            bool: 是否成功
        """
        with self._lock:
            if session_id in self._active_sessions:
                del self._active_sessions[session_id]

            conn = sqlite3.connect(str(self._db_path))
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.commit()
            conn.close()
            return True

    def cleanup_expired_sessions(self) -> int:
        """清理过期会话

        Returns:
            int: 清理数量
        """
        with self._lock:
            expired_ids = [
                sid for sid, session in self._active_sessions.items()
                if self._is_session_expired(session)
            ]
            for sid in expired_ids:
                del self._active_sessions[sid]

            cutoff_time = time.time() - self.session_ttl
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.execute("DELETE FROM sessions WHERE last_active < ?", (cutoff_time,))
            count = cursor.rowcount
            conn.commit()
            conn.close()
            return count

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息

        Returns:
            Dict: 统计数据
        """
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.execute("SELECT COUNT(*) FROM sessions")
            total_count = cursor.fetchone()[0]
            conn.close()

            return {
                "active_sessions": len(self._active_sessions),
                "total_sessions": total_count,
                "session_ttl": self.session_ttl,
                "max_turns": self.max_turns
            }

    def _is_session_expired(self, session: ConversationSession) -> bool:
        """检查会话是否过期"""
        return (time.time() - session.last_active) > self.session_ttl

    def _compress_session(self, session: ConversationSession) -> None:
        """压缩会话
        
        如果启用了异步压缩且线程池可用，则在后台线程执行压缩；
        否则同步执行压缩。
        """
        if self._compress_executor:
            # 异步压缩：提交到线程池
            self._compress_executor.submit(self._do_compress, session.session_id)
            logger.debug_ctx(
                "异步压缩已提交",
                session_id=session.session_id,
                extra_data={"turn_count": session.turn_count}
            )
        else:
            # 同步压缩
            self._do_compress(session.session_id)
    
    def _do_compress(self, session_id: str) -> None:
        """执行实际的压缩操作"""
        try:
            self.compress_context(session_id)
        except Exception as e:
            logger.error_ctx(
                "压缩会话失败",
                session_id=session_id,
                extra_data={"error": str(e)}
            )

    def _format_full_history(self, messages: List[Message]) -> str:
        """格式化完整历史"""
        history_parts = []
        for msg in messages:
            role_label = "用户" if msg.role == MessageRole.USER.value else "助手"
            history_parts.append(f"{role_label}: {msg.content}")
        return "\n".join(history_parts)

    def _generate_summary(self, messages: List[Message], level: str = "light") -> str:
        """生成对话摘要
        
        优先使用 LLM 生成高质量摘要，如果 LLM 不可用则降级到规则驱动
        
        Args:
            messages: 消息列表
            level: 压缩级别（"light" 或 "deep"）
        
        Returns:
            str: 摘要文本
        """
        if not messages:
            return ""

        # 尝试使用 LLM 生成摘要
        if self.llm_client:
            try:
                return self._generate_llm_summary(messages, level)
            except Exception as e:
                logger.warning_ctx(
                    "LLM摘要生成失败，降级到规则驱动",
                    extra_data={"error": str(e)}
                )

        # 降级到规则驱动摘要
        return self._generate_rule_based_summary(messages, level)

    def _generate_llm_summary(self, messages: List[Message], level: str = "light") -> str:
        """使用 LLM 生成对话摘要
        
        Args:
            messages: 消息列表
            level: 压缩级别（"light" 或 "deep"）
        
        Returns:
            str: 摘要文本
        """
        # 格式化对话历史
        history_parts = []
        for msg in messages:
            role_label = "用户" if msg.role == MessageRole.USER.value else "助手"
            history_parts.append(f"{role_label}: {msg.content}")
        
        conversation_text = "\n".join(history_parts)
        
        # 根据压缩级别构建不同的 prompt
        if level == "deep":
            prompt = f"""请为以下 Dota 2 助手对话生成极简摘要，仅保留核心决策和关键结论：

{conversation_text}

请用一句话总结（不超过30字）："""
            max_tokens = 60
        else:  # light
            prompt = f"""请为以下 Dota 2 助手对话生成简洁的摘要，提取关键信息（讨论的英雄、话题、结论等）：

{conversation_text}

请用一句话总结（不超过50字）："""
            max_tokens = 100

        # 调用 LLM
        response = self.llm_client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=max_tokens
        )
        
        summary = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        
        if summary:
            return summary
        
        raise ValueError("LLM返回空摘要")

    def _generate_rule_based_summary(self, messages: List[Message], level: str = "light") -> str:
        """规则驱动的对话摘要（降级方案）
        
        Args:
            messages: 消息列表
            level: 压缩级别（"light" 或 "deep"）
        
        Returns:
            str: 摘要文本
        """
        entities_mentioned = []
        topics_discussed = []

        for msg in messages:
            content_lower = msg.content.lower()
            if "hero" in msg.metadata.get("entities", []):
                entities_mentioned.extend(msg.metadata["entities"])

            if any(kw in content_lower for kw in ["克制", "counter", "推荐"]):
                topics_discussed.append("英雄克制")
            elif any(kw in content_lower for kw in ["出装", "装备", "item"]):
                topics_discussed.append("出装推荐")
            elif any(kw in content_lower for kw in ["技能", "加点", "skill"]):
                topics_discussed.append("技能加点")

        summary_parts = []
        if entities_mentioned:
            hero_names = list(set([e.get("name", "") for e in entities_mentioned if e.get("name")]))
            if hero_names:
                summary_parts.append(f"讨论了英雄: {', '.join(hero_names)}")

        if topics_discussed:
            summary_parts.append(f"话题: {', '.join(topics_discussed)}")

        # 深度压缩时只保留核心信息
        if level == "deep":
            if hero_names:
                return f"讨论英雄: {', '.join(hero_names[:3])}"  # 最多3个英雄
            elif topics_discussed:
                return f"话题: {topics_discussed[0]}"  # 只保留第一个话题
            return "多轮对话"
        
        return "；".join(summary_parts) if summary_parts else "进行了多轮对话"

    def _save_session_to_db(self, session: ConversationSession) -> None:
        """保存会话到数据库"""
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("""
                INSERT OR REPLACE INTO sessions (session_id, data, created_at, last_active, turn_count)
                VALUES (?, ?, ?, ?, ?)
            """, (
                session.session_id,
                json.dumps(session.to_dict(), ensure_ascii=False),
                session.created_at,
                session.last_active,
                session.turn_count
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error_ctx(
                "保存会话失败",
                session_id=None,
                extra_data={"error": str(e)}
            )

    def _load_session_from_db(self, session_id: str) -> Optional[ConversationSession]:
        """从数据库加载会话"""
        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.execute("SELECT data FROM sessions WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            conn.close()

            if row is None:
                return None

            data = json.loads(row[0])
            return ConversationSession.from_dict(data)
        except Exception as e:
            logger.error_ctx(
                "加载会话失败",
                session_id=None,
                extra_data={"error": str(e)}
            )
            return None