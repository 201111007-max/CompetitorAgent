"""会话持久化管理 — 替代内存字典，支持进程重启后会话不丢失

存储路径：~/.dota_helper/data/sessions/{session_id}.json

每个会话文件包含：
- session_id: 会话唯一标识
- title: 会话标题（首条消息前 20 字符）
- created_at: 创建时间戳
- updated_at: 更新时间戳
- messages: 消息列表（role + content + created_at）
"""
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from dota_helper.observability.logger import get_logger

logger = get_logger("agent.session_manager")


@dataclass
class ChatMessage:
    """聊天消息

    Attributes:
        conversation_id: 对话 ID
        role: 消息角色（user / agent）
        content: 消息内容
        created_at: 创建时间戳
    """
    conversation_id: str = ""
    role: str = ""
    content: str = ""
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典

        Returns:
            Dict[str, Any]: 消息字典
        """
        return {
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMessage":
        """从字典创建 ChatMessage

        Args:
            data: 消息字典

        Returns:
            ChatMessage: 消息实例
        """
        return cls(
            conversation_id=data.get("conversation_id", ""),
            role=data.get("role", ""),
            content=data.get("content", ""),
            created_at=data.get("created_at", 0.0),
        )


@dataclass
class ChatSession:
    """聊天会话

    Attributes:
        session_id: 会话唯一标识
        title: 会话标题
        created_at: 创建时间戳
        updated_at: 更新时间戳
        messages: 消息列表
    """
    session_id: str = ""
    title: str = "新会话"
    created_at: float = 0.0
    updated_at: float = 0.0
    messages: List[ChatMessage] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典

        Returns:
            Dict[str, Any]: 会话字典
        """
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [msg.to_dict() for msg in self.messages],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatSession":
        """从字典创建 ChatSession

        Args:
            data: 会话字典

        Returns:
            ChatSession: 会话实例
        """
        return cls(
            session_id=data.get("session_id", ""),
            title=data.get("title", "新会话"),
            created_at=data.get("created_at", 0.0),
            updated_at=data.get("updated_at", 0.0),
            messages=[ChatMessage.from_dict(m) for m in data.get("messages", [])],
        )


@dataclass
class ChatSessionSummary:
    """聊天会话摘要（用于历史列表展示）

    Attributes:
        session_id: 会话唯一标识
        title: 会话标题
        updated_at: 更新时间戳
    """
    session_id: str = ""
    title: str = "新会话"
    updated_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典

        Returns:
            Dict[str, Any]: 会话摘要字典
        """
        return {
            "session_id": self.session_id,
            "title": self.title,
            "updated_at": self.updated_at,
        }


class SessionManager:
    """会话持久化管理，替代内存字典

    将每个会话保存为 JSON 文件，支持进程重启后恢复。

    Args:
        data_dir: 数据根目录，默认 ~/.dota_helper/data/sessions/
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        """初始化会话管理器

        Args:
            data_dir: 数据根目录，默认为 ~/.dota_helper/data/sessions/
        """
        if data_dir is not None:
            self._data_dir = data_dir
        else:
            self._data_dir = Path.home() / ".dota_helper" / "data" / "sessions"

        # 确保目录存在
        self._data_dir.mkdir(parents=True, exist_ok=True)

        logger.info("会话管理器初始化: data_dir=%s", self._data_dir)

    async def create_session(self) -> str:
        """创建新会话，返回 session_id

        Returns:
            str: 新会话 ID
        """
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        now = time.time()

        session = ChatSession(
            session_id=session_id,
            title="新会话",
            created_at=now,
            updated_at=now,
        )

        await self._save_session(session)
        logger.info("创建新会话: session_id=%s", session_id)
        return session_id

    async def get_session(self, session_id: str) -> Optional[ChatSession]:
        """获取会话

        Args:
            session_id: 会话 ID

        Returns:
            Optional[ChatSession]: 会话实例，不存在返回 None
        """
        file_path = self._data_dir / f"{session_id}.json"
        if not file_path.exists():
            return None

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            return ChatSession.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("会话文件损坏: session_id=%s, error=%s", session_id, str(e))
            return None

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        conversation_id: Optional[str] = None,
    ) -> None:
        """追加消息到会话

        Args:
            session_id: 会话 ID
            role: 消息角色（user / agent）
            content: 消息内容
            conversation_id: 对话 ID（可选）

        Raises:
            ValueError: 会话不存在
        """
        session = await self.get_session(session_id)
        if session is None:
            raise ValueError(f"会话不存在: {session_id}")

        now = time.time()
        if not conversation_id:
            conversation_id = f"conv_{uuid.uuid4().hex[:12]}"

        # 首条用户消息自动设置为会话标题
        message = ChatMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=now,
        )
        session.messages.append(message)
        session.updated_at = now

        # 首条用户消息更新标题
        if role == "user" and session.title == "新会话":
            session.title = content[:20] or "新会话"

        await self._save_session(session)
        logger.debug("追加消息: session=%s, role=%s, len=%d", session_id, role, len(content))

    async def list_sessions(self, limit: int = 50) -> List[ChatSessionSummary]:
        """列出最近会话

        按更新时间降序排列。

        Args:
            limit: 最大返回数量

        Returns:
            List[ChatSessionSummary]: 会话摘要列表
        """
        summaries = []
        for file_path in self._data_dir.glob("*.json"):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                summaries.append(ChatSessionSummary(
                    session_id=data.get("session_id", ""),
                    title=data.get("title", "新会话"),
                    updated_at=data.get("updated_at", 0.0),
                ))
            except (json.JSONDecodeError, KeyError):
                continue

        # 按更新时间降序
        summaries.sort(key=lambda s: s.updated_at, reverse=True)
        return summaries[:limit]

    async def delete_session(self, session_id: str) -> None:
        """删除会话

        Args:
            session_id: 会话 ID
        """
        file_path = self._data_dir / f"{session_id}.json"
        if file_path.exists():
            file_path.unlink()
            logger.info("删除会话: session_id=%s", session_id)
        else:
            logger.warning("会话不存在，跳过删除: session_id=%s", session_id)

    async def _save_session(self, session: ChatSession) -> None:
        """保存会话到文件

        Args:
            session: 会话实例
        """
        file_path = self._data_dir / f"{session.session_id}.json"
        file_path.write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @property
    def data_dir(self) -> Path:
        """数据目录路径

        Returns:
            Path: 数据目录路径
        """
        return self._data_dir
