"""上下文增强器 - 多轮对话上下文理解

实现指代消解、意图推断、实体提取和上下文注入功能
"""

import re
import json
from typing import Dict, List, Any, Optional
from pathlib import Path
import sys

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.conversation_manager import ConversationSession, Message, MessageRole


class ContextAugmenter:
    """上下文增强器

    功能：
    - 指代消解：理解代词指向
    - 意图推断：推断用户真实意图
    - 实体提取：识别英雄名、物品名等
    - 上下文注入：将对话历史注入到查询中
    """

    PRONOUN_MAP = {
        "那": "previous_context",
        "这": "current_context",
        "它": "last_entity",
        "他": "last_entity",
        "她": "last_entity",
        "这个": "current_entity",
        "那个": "previous_entity",
    }

    INTENT_KEYWORDS = {
        "recommend_heroes": ["克制", "counter", "推荐", "选什么英雄", "什么英雄", "克制谁"],
        "recommend_items": ["出装", "装备", "item", "build", "出什么"],
        "recommend_skills": ["技能", "加点", "skill", "ability", "怎么加"],
        "analyze_matchups": ["对线", "对拼", "打谁好", "克制关系"],
    }

    TOPIC_KEYWORDS = {
        "counter": ["克制", "counter", "克制谁", "被谁克制"],
        "items": ["出装", "装备", "item", "build"],
        "skills": ["技能", "加点", "skill", "ability"],
        "general": [],
    }

    def __init__(self, llm_client=None):
        """初始化上下文增强器

        Args:
            llm_client: LLM 客户端（可选，用于高级指代消解）
        """
        self.llm_client = llm_client
        self._known_heroes: set = set()

    def load_known_heroes(self, heroes: List[str]) -> None:
        """加载已知英雄列表

        Args:
            heroes: 英雄名称列表
        """
        self._known_heroes = set(h.lower() for h in heroes)

    def augment_query(
        self,
        query: str,
        session: ConversationSession
    ) -> Dict[str, Any]:
        """增强查询 - 注入对话上下文

        Args:
            query: 用户原始查询
            session: 当前会话

        Returns:
            Dict: 增强后的查询和上下文
        """
        context = self._extract_context(session)

        resolved_query = self.resolve_pronouns(query, context)

        inferred_intent = self.infer_intent(resolved_query, context)

        augmented_query = self._build_augmented_query(
            resolved_query, context, inferred_intent
        )

        entities = self.extract_entities(resolved_query)

        return {
            "original_query": query,
            "augmented_query": augmented_query,
            "context": {
                "conversation_history": context.get("conversation_history", []),
                "current_heroes": context.get("current_heroes", {"our": [], "enemy": []}),
                "current_topic": context.get("current_topic", "general"),
                "entities": entities,
                "inferred_intent": inferred_intent,
                "turn_count": context.get("turn_count", 0)
            },
            "entities": entities,
            "inferred_intent": inferred_intent
        }

    def resolve_pronouns(self, query: str, context: Dict[str, Any]) -> str:
        """指代消解

        Args:
            query: 用户查询
            context: 对话上下文

        Returns:
            str: 消解后的查询
        """
        resolved = query

        current_heroes = context.get("current_heroes", {"our": [], "enemy": []})
        all_heroes = current_heroes.get("our", []) + current_heroes.get("enemy", [])

        for pronoun, replacement_type in self.PRONOUN_MAP.items():
            if pronoun in resolved:
                if replacement_type in ["last_entity", "previous_entity", "current_entity"]:
                    if all_heroes:
                        last_hero = all_heroes[-1]
                        resolved = resolved.replace(pronoun, last_hero, 1)
                elif replacement_type in ["previous_context", "current_context"]:
                    current_topic = context.get("current_topic", "general")
                    if current_topic != "general":
                        topic_map = {
                            "counter": "克制英雄",
                            "items": "出装",
                            "skills": "技能加点"
                        }
                        topic_text = topic_map.get(current_topic, "")
                        if topic_text:
                            resolved = resolved.replace(pronoun, topic_text, 1)

        return resolved

    def infer_intent(self, query: str, context: Dict[str, Any]) -> str:
        """推断用户意图

        Args:
            query: 用户查询
            context: 对话上下文

        Returns:
            str: 意图类型
        """
        query_lower = query.lower()

        for intent, keywords in self.INTENT_KEYWORDS.items():
            if any(kw in query_lower for kw in keywords):
                return intent

        if any(word in query_lower for word in ["呢", "呢？", "那", "然后"]):
            current_topic = context.get("current_topic", "general")
            topic_intent_map = {
                "counter": "recommend_heroes",
                "items": "recommend_items",
                "skills": "recommend_skills"
            }
            return topic_intent_map.get(current_topic, "general")

        return "general"

    def extract_entities(self, text: str) -> List[Dict[str, str]]:
        """提取实体

        Args:
            text: 文本

        Returns:
            List[Dict]: 实体列表
        """
        entities = []

        if self._known_heroes:
            text_lower = text.lower()
            for hero_name in self._known_heroes:
                if hero_name in text_lower:
                    entities.append({
                        "type": "hero",
                        "name": hero_name,
                        "text": hero_name
                    })
        else:
            hero_pattern = re.compile(
                r'(?:敌方|对面|对方|我方|我们|己方)?[\s:：]*'
                r'([\u4e00-\u9fa5]{2,4}|[a-z_]+)'
            )

            matches = hero_pattern.findall(text)
            for match in matches:
                if len(match) >= 2:
                    entities.append({
                        "type": "hero",
                        "name": match,
                        "text": match
                    })

        return entities

    def detect_topic(self, query: str) -> str:
        """检测话题

        Args:
            query: 用户查询

        Returns:
            str: 话题类型
        """
        query_lower = query.lower()

        for topic, keywords in self.TOPIC_KEYWORDS.items():
            if topic == "general":
                continue
            if any(kw in query_lower for kw in keywords):
                return topic

        return "general"

    def _extract_context(self, session: ConversationSession) -> Dict[str, Any]:
        """提取会话上下文"""
        return {
            "conversation_history": [msg.to_dict() for msg in session.get_recent_messages(10)],
            "current_heroes": session.get_current_heroes(),
            "current_topic": session.get_current_topic(),
            "turn_count": session.turn_count,
            "entity_history": session.entity_history
        }

    def _build_augmented_query(
        self,
        resolved_query: str,
        context: Dict[str, Any],
        inferred_intent: str
    ) -> str:
        """构建增强查询"""
        current_heroes = context.get("current_heroes", {"our": [], "enemy": []})

        has_hero_context = current_heroes.get("our") or current_heroes.get("enemy")

        is_short_query = len(resolved_query) < 10
        has_pronoun = any(p in resolved_query for p in self.PRONOUN_MAP.keys())

        if has_hero_context and (is_short_query or has_pronoun):
            hero_parts = []
            if current_heroes.get("enemy"):
                hero_parts.append(f"敌方{','.join(current_heroes['enemy'])}")
            if current_heroes.get("our"):
                hero_parts.append(f"己方{','.join(current_heroes['our'])}")

            if hero_parts:
                augmented = f"{resolved_query}（上下文：{'，'.join(hero_parts)}）"
                return augmented

        return resolved_query

    def format_history_for_prompt(self, history: List[Dict[str, Any]]) -> str:
        """格式化对话历史用于 prompt 注入

        Args:
            history: 对话历史列表

        Returns:
            str: 格式化后的历史文本
        """
        if not history:
            return "无对话历史"

        history_parts = []
        for msg in history:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            role_label = "用户" if role == MessageRole.USER.value else "助手"
            history_parts.append(f"{role_label}: {content}")

        return "\n".join(history_parts) if history_parts else "无对话历史"