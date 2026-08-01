"""RAG 插件 — 在 LLM 调用前自动注入相关知识

通过 Plugin 的 before_llm_call 钩子，在每轮 LLM 调用前自动检索知识库，
将相关知识注入到 system 消息末尾，增强 LLM 的领域知识。

设计要点：
- 去重机制：同一 query 不重复检索，同一内容不重复注入
- 阈值过滤：相似度低于 0.4 的不注入，避免噪声
- 注入位置：追加到已有 system 消息末尾
- 不阻塞：检索失败或超时不影响主流程，静默跳过
"""
from typing import Any, Dict, List, Optional

from dota_helper.agent.plugin import Plugin
from dota_helper.agent.rag_engine import RagEngine
from dota_helper.observability.logger import get_logger

logger = get_logger("agent.rag_plugin")

_DEFAULT_THRESHOLD = 0.4
_DEFAULT_TOP_K = 2


class RagPlugin(Plugin):
    """RAG 插件 — 在 LLM 调用前自动注入相关知识

    通过 before_llm_call 钩子，从用户消息中提取查询意图，
    检索知识库后将相关知识注入到 system 消息末尾。

    Args:
        engine: RagEngine 实例
        threshold: 注入最低相似度阈值（默认 0.4）
        top_k: 每次注入的参考数量（默认 2）
    """

    def __init__(
        self,
        engine: RagEngine,
        threshold: float = _DEFAULT_THRESHOLD,
        top_k: int = _DEFAULT_TOP_K,
    ) -> None:
        super().__init__()
        self._engine = engine
        self._threshold = threshold
        self._top_k = top_k

        # 去重缓存
        self._last_query: str = ""
        self._last_injected: str = ""

        logger.info(
            "RAG 插件初始化: threshold=%.2f, top_k=%d",
            threshold, top_k,
        )

    @property
    def name(self) -> str:
        return "RagPlugin"

    async def before_llm_call(
        self, messages: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """在 LLM 调用前注入 RAG 检索结果

        从消息列表中提取最后一条 user 消息作为查询，
        检索知识库后将相关知识注入到 system 消息末尾。

        Args:
            messages: 当前消息列表

        Returns:
            List[Dict[str, str]]: 修改后的消息列表
        """
        # 提取最后一条 user 消息
        last_user = self._get_last_user_message(messages)
        if not last_user:
            return messages

        # 去重：同一 query 不重复检索
        if last_user == self._last_query:
            return messages
        self._last_query = last_user

        # 检索知识库
        try:
            results = self._engine.search(last_user, top_k=self._top_k)
        except Exception as e:
            logger.warning("RAG 检索失败（静默跳过）: %s", str(e))
            return messages

        # 阈值过滤
        if not results or results[0].get("score", 0.0) < self._threshold:
            logger.debug(
                "RAG 结果低于阈值: score=%.3f < threshold=%.2f",
                results[0].get("score", 0.0) if results else 0.0,
                self._threshold,
            )
            return messages

        # 格式化上下文
        context = self._engine.format_context(results)
        if not context:
            return messages

        # 去重：同一内容不重复注入
        if context == self._last_injected:
            return messages
        self._last_injected = context

        # 注入到 system 消息末尾
        messages = self._inject_context(messages, context)

        logger.info(
            "RAG 知识已注入: query_len=%d, context_len=%d, top_score=%.3f",
            len(last_user), len(context), results[0].get("score", 0.0),
        )
        return messages

    def _get_last_user_message(
        self, messages: List[Dict[str, str]]
    ) -> str:
        """提取消息列表中最后一条 user 角色的消息内容

        Args:
            messages: 消息列表

        Returns:
            str: 最后一条 user 消息内容，无 user 消息返回空字符串
        """
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return ""

    def _inject_context(
        self,
        messages: List[Dict[str, str]],
        context: str,
    ) -> List[Dict[str, str]]:
        """将 RAG 上下文注入到 system 消息末尾

        找到最后一条 system 消息，将 RAG 上下文追加到其 content 末尾。
        如果没有 system 消息，在列表开头插入一条新的 system 消息。

        Args:
            messages: 原始消息列表
            context: RAG 上下文文本

        Returns:
            List[Dict[str, str]]: 修改后的消息列表
        """
        # 找到最后一条 system 消息
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "system":
                messages[i] = {
                    "role": "system",
                    "content": messages[i]["content"] + "\n\n" + context,
                }
                return messages

        # 没有 system 消息，在开头插入
        messages.insert(0, {"role": "system", "content": context})
        return messages

    def reset(self) -> None:
        """重置去重缓存（用于测试或新会话）"""
        self._last_query = ""
        self._last_injected = ""
        logger.debug("RAG 插件去重缓存已重置")
