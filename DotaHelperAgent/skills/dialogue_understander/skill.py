"""多轮对话理解 Skill

实现指代消解、意图推断、实体提取，输出结构化理解结果。
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from core.conversation_manager import ConversationSession, Message, MessageRole
from ..base import BaseSkill, SkillContext, SkillResult

logger = logging.getLogger(__name__)


class DialogueUnderstanderSkill(BaseSkill):
    """多轮对话理解 Skill

    输入: {"history": [...], "current_input": "..."}
    输出: {"enhanced_query": "...", "intent": "...", "entities": {...}, "context_used": bool}
    """

    def __init__(
        self,
        llm_client: Any,
        context_augmenter: Optional[Any] = None,
        prompt_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name="dialogue_understander",
            version="1.0.0",
            description="多轮对话上下文理解（指代消解、意图推断、实体提取）",
            **kwargs,
        )
        self.llm_client = llm_client
        self.context_augmenter = context_augmenter
        self.prompt_manager = prompt_manager

    async def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """执行多轮对话理解"""
        history = input_data.get("history", [])
        current_input = input_data.get("current_input", "")

        prompt = self._build_prompt(history, current_input)
        response = await self._llm_generate(prompt)

        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            parsed = self._parse_fallback(response, current_input)

        return SkillResult(
            success=True,
            data=parsed,
            confidence=0.8,
        )

    async def _fallback(
        self,
        input_data: Dict[str, Any],
        context: Optional[SkillContext] = None,
        error: Optional[Exception] = None,
    ) -> SkillResult:
        """降级到规则驱动的 ContextAugmenter"""
        history = input_data.get("history", [])
        current_input = input_data.get("current_input", "")

        if self.context_augmenter:
            try:
                session = self._build_session(history)
                result = self.context_augmenter.augment_query(current_input, session)
                return SkillResult(
                    success=True,
                    data={
                        "enhanced_query": result.get("augmented_query", current_input),
                        "intent": result.get("inferred_intent", "general"),
                        "entities": result.get("entities", {}),
                        "context_used": bool(result.get("context", {}).get("conversation_history", [])),
                    },
                    confidence=0.5,
                )
            except Exception as e:
                logger.warning(f"ContextAugmenter fallback failed: {e}")

        return SkillResult(
            success=True,
            data={
                "enhanced_query": current_input,
                "intent": "general",
                "entities": {"heroes": [], "items": [], "skills": []},
                "context_used": False,
            },
            confidence=0.3,
        )

    async def _llm_generate(self, prompt: str) -> str:
        """调用 LLM 生成文本（避免阻塞事件循环）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.llm_client.complete, prompt)

    def _build_session(self, history: List[Dict[str, str]]) -> ConversationSession:
        """从历史消息构建 ConversationSession"""
        session = ConversationSession(session_id="fallback")
        for msg in history:
            role_str = msg.get("role", MessageRole.USER.value)
            session.add_message(Message(
                role=role_str,
                content=msg.get("content", ""),
            ))
        return session

    def _build_prompt(
        self,
        history: List[Dict[str, str]],
        current_input: str,
    ) -> str:
        """构建 Prompt"""
        history_text = self._format_history(history)
        if self.prompt_manager:
            return self.prompt_manager.get_prompt(
                "dialogue_understand",
                variables={
                    "history": history_text,
                    "current_input": current_input,
                },
            )

        return f"""你是一名 Dota 2 助手，需要理解用户的对话上下文。

## 对话历史
{history_text}

## 当前用户输入
{current_input}

请以 JSON 格式输出，不要包含其他内容：
{{
  "enhanced_query": "消解后的完整查询",
  "intent": "recommend_heroes | recommend_items | recommend_skills | analyze_matchups | general",
  "entities": {{
    "heroes": ["英雄列表"],
    "items": ["物品列表"],
    "skills": ["技能列表"]
  }},
  "context_used": true/false
}}"""

    def _format_history(self, history: List[Dict[str, str]]) -> str:
        """格式化对话历史"""
        lines = []
        for msg in history[-10:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n".join(lines) if lines else "（无历史对话）"

    def _parse_fallback(self, response: str, current_input: str) -> Dict[str, Any]:
        """LLM 返回非 JSON 时的兜底解析"""
        return {
            "enhanced_query": current_input,
            "intent": "unknown",
            "entities": {"heroes": [], "items": [], "skills": []},
            "context_used": False,
            "raw_response": response,
        }
