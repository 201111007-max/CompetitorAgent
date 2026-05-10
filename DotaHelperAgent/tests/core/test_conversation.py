"""多轮对话功能单元测试"""

import pytest
import tempfile
import shutil
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock

import sys
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.conversation_manager import ConversationManager, Message, MessageRole, ConversationSession
from core.context_augmenter import ContextAugmenter


@pytest.fixture
def temp_dir():
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def conversation_manager(temp_dir):
    return ConversationManager(
        storage_dir=temp_dir,
        session_ttl=1800,
        max_turns=20,
        max_context_turns=5
    )


@pytest.fixture
def context_augmenter():
    return ContextAugmenter()


@pytest.fixture
def sample_session():
    session = ConversationSession(session_id="test_session_001")
    session.add_message(Message(role="user", content="推荐克制敌法的英雄"))
    session.add_message(Message(role="assistant", content="推荐斧王、军团战士"))
    session.add_message(Message(role="user", content="那出装呢？"))
    session.add_message(Message(role="assistant", content="推荐跳刀、黑皇杖"))
    session.update_context_state("current_heroes", {"our": ["敌法"], "enemy": ["斧王"]})
    session.update_context_state("current_topic", "counter")
    return session


class TestMessage:
    def test_create_message(self):
        msg = Message(role="user", content="测试消息")
        assert msg.role == "user"
        assert msg.content == "测试消息"
        assert msg.timestamp > 0
        assert msg.metadata == {}

    def test_message_to_dict(self):
        msg = Message(role="user", content="测试", metadata={"key": "value"})
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "测试"
        assert d["metadata"] == {"key": "value"}

    def test_message_from_dict(self):
        data = {
            "role": "assistant",
            "content": "回复",
            "timestamp": 1234567890.0,
            "metadata": {"score": 0.9}
        }
        msg = Message.from_dict(data)
        assert msg.role == "assistant"
        assert msg.content == "回复"
        assert msg.timestamp == 1234567890.0
        assert msg.metadata == {"score": 0.9}


class TestConversationSession:
    def test_add_message(self):
        session = ConversationSession(session_id="test")
        session.add_message(Message(role="user", content="你好"))
        assert len(session.messages) == 1
        assert session.turn_count == 1

    def test_add_multiple_messages(self):
        session = ConversationSession(session_id="test")
        session.add_message(Message(role="user", content="消息1"))
        session.add_message(Message(role="assistant", content="回复1"))
        session.add_message(Message(role="user", content="消息2"))
        assert len(session.messages) == 3
        assert session.turn_count == 2

    def test_get_recent_messages(self):
        session = ConversationSession(session_id="test")
        for i in range(15):
            session.add_message(Message(role="user", content=f"消息{i}"))
        recent = session.get_recent_messages(limit=5)
        assert len(recent) == 5
        assert recent[-1].content == "消息14"

    def test_update_context_state(self):
        session = ConversationSession(session_id="test")
        session.update_context_state("current_topic", "items")
        assert session.context_state["current_topic"] == "items"

    def test_get_current_heroes(self):
        session = ConversationSession(session_id="test")
        session.update_context_state("current_heroes", {"our": ["敌法"], "enemy": ["斧王"]})
        heroes = session.get_current_heroes()
        assert heroes["our"] == ["敌法"]
        assert heroes["enemy"] == ["斧王"]

    def test_track_entity(self):
        session = ConversationSession(session_id="test")
        session.track_entity("hero", {"name": "敌法", "type": "strength"})
        assert "hero" in session.entity_history
        assert len(session.entity_history["hero"]) == 1
        assert session.entity_history["hero"][0]["name"] == "敌法"


class TestConversationManager:
    def test_create_session(self, conversation_manager):
        session = conversation_manager.create_session("test_001")
        assert session.session_id == "test_001"
        assert session.turn_count == 0

    def test_get_or_create_session(self, conversation_manager):
        session1 = conversation_manager.get_or_create_session("test_002")
        session2 = conversation_manager.get_or_create_session("test_002")
        assert session1.session_id == session2.session_id

    def test_add_message(self, conversation_manager):
        conversation_manager.create_session("test_003")
        msg = Message(role="user", content="测试消息")
        result = conversation_manager.add_message("test_003", msg)
        assert result is True

    def test_add_message_to_nonexistent_session(self, conversation_manager):
        msg = Message(role="user", content="测试")
        result = conversation_manager.add_message("nonexistent", msg)
        assert result is False

    def test_get_history(self, conversation_manager):
        conversation_manager.create_session("test_004")
        for i in range(5):
            conversation_manager.add_message("test_004", Message(role="user", content=f"消息{i}"))
        history = conversation_manager.get_history("test_004", limit=3)
        assert len(history) == 3

    def test_get_context(self, conversation_manager):
        conversation_manager.create_session("test_005")
        conversation_manager.add_message("test_005", Message(role="user", content="测试"))
        context = conversation_manager.get_context("test_005")
        assert "conversation_history" in context
        assert "current_heroes" in context
        assert context["turn_count"] == 1

    def test_update_context_state(self, conversation_manager):
        conversation_manager.create_session("test_006")
        result = conversation_manager.update_context_state("test_006", "topic", "items")
        assert result is True

    def test_get_stats(self, conversation_manager):
        conversation_manager.create_session("stats_001")
        conversation_manager.create_session("stats_002")
        stats = conversation_manager.get_stats()
        assert stats["active_sessions"] >= 2
        assert stats["total_sessions"] >= 2

    def test_session_persistence(self, conversation_manager):
        conversation_manager.create_session("persist_001")
        conversation_manager.add_message("persist_001", Message(role="user", content="持久化测试"))
        
        new_manager = ConversationManager(
            storage_dir=conversation_manager.storage_dir,
            session_ttl=1800
        )
        session = new_manager.get_session("persist_001")
        assert session is not None
        assert len(session.messages) == 1

    def test_close_session(self, conversation_manager):
        conversation_manager.create_session("close_001")
        result = conversation_manager.close_session("close_001")
        assert result is True
        session = conversation_manager.get_session("close_001")
        assert session is None

    def test_cleanup_expired_sessions(self, conversation_manager):
        conversation_manager.create_session("expire_001")
        session = conversation_manager._active_sessions["expire_001"]
        session.last_active = time.time() - 3600
        
        count = conversation_manager.cleanup_expired_sessions()
        assert "expire_001" not in conversation_manager._active_sessions


class TestContextAugmenter:
    def test_extract_entities_with_known_heroes(self, context_augmenter):
        context_augmenter.load_known_heroes(["敌法", "斧王", "军团战士"])
        entities = context_augmenter.extract_entities("推荐克制敌法的英雄")
        assert len(entities) > 0
        assert any(e["name"] == "敌法" for e in entities)

    def test_extract_entities_without_known_heroes(self, context_augmenter):
        entities = context_augmenter.extract_entities("推荐英雄")
        assert isinstance(entities, list)

    def test_infer_intent_recommend_heroes(self, context_augmenter):
        intent = context_augmenter.infer_intent("推荐克制敌法的英雄", {})
        assert intent == "recommend_heroes"

    def test_infer_intent_recommend_items(self, context_augmenter):
        intent = context_augmenter.infer_intent("敌法应该出什么装备", {})
        assert intent == "recommend_items"

    def test_infer_intent_recommend_skills(self, context_augmenter):
        intent = context_augmenter.infer_intent("敌法技能怎么加点", {})
        assert intent == "recommend_skills"

    def test_infer_intent_from_context(self, context_augmenter):
        context = {"current_topic": "items"}
        intent = context_augmenter.infer_intent("那出装呢", context)
        assert intent == "recommend_items"

    def test_detect_topic_counter(self, context_augmenter):
        topic = context_augmenter.detect_topic("什么英雄克制敌法")
        assert topic == "counter"

    def test_detect_topic_items(self, context_augmenter):
        topic = context_augmenter.detect_topic("推荐出装")
        assert topic == "items"

    def test_detect_topic_skills(self, context_augmenter):
        topic = context_augmenter.detect_topic("技能加点推荐")
        assert topic == "skills"

    def test_resolve_pronouns(self, context_augmenter):
        context = {
            "current_heroes": {"our": ["敌法"], "enemy": ["斧王"]},
            "current_topic": "counter"
        }
        resolved = context_augmenter.resolve_pronouns("它克制谁", context)
        assert "斧王" in resolved or "敌法" in resolved

    def test_augment_query(self, context_augmenter, sample_session):
        result = context_augmenter.augment_query("推荐出装", sample_session)
        assert "augmented_query" in result
        assert "context" in result
        assert "inferred_intent" in result
        assert result["context"]["turn_count"] == 2

    def test_format_history_for_prompt(self, context_augmenter):
        history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好，有什么可以帮助你的？"}
        ]
        formatted = context_augmenter.format_history_for_prompt(history)
        assert "用户: 你好" in formatted
        assert "助手: 你好，有什么可以帮助你的？" in formatted

    def test_format_history_for_empty(self, context_augmenter):
        formatted = context_augmenter.format_history_for_prompt([])
        assert formatted == "无对话历史"

    def test_format_history_with_invalid_messages(self, context_augmenter):
        history = [None, {"role": "user", "content": "有效消息"}, "invalid"]
        formatted = context_augmenter.format_history_for_prompt(history)
        assert "用户: 有效消息" in formatted

    def test_build_augmented_query_with_context(self, context_augmenter):
        context = {
            "current_heroes": {"our": ["敌法"], "enemy": ["斧王"]},
            "current_topic": "counter"
        }
        augmented = context_augmenter._build_augmented_query("推荐", context, "recommend_heroes")
        assert "敌法" in augmented or "斧王" in augmented

    def test_load_known_heroes(self, context_augmenter):
        context_augmenter.load_known_heroes(["敌法", "斧王"])
        assert "敌法" in context_augmenter._known_heroes
        assert "斧王" in context_augmenter._known_heroes
