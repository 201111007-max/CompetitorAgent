"""知识查询 Skill

基于向量检索和知识融合引擎，直接生成自然语言答案。
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from ..base import BaseSkill, SkillContext, SkillResult

logger = logging.getLogger(__name__)


class KnowledgeQuerySkill(BaseSkill):
    """知识查询 Skill

    输入: 用户查询字符串（如"PA 怎么出装？"）
    输出: {"answer": "自然语言回答", "sources": [...]}
    """

    def __init__(
        self,
        llm_client: Any,
        vector_store: Any,
        fusion_engine: Optional[Any] = None,
        top_k: int = 5,
        prompt_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name="knowledge_query",
            version="1.0.0",
            description="检索攻略文档并生成回答",
            **kwargs,
        )
        self.llm_client = llm_client
        self.vector_store = vector_store
        self.fusion_engine = fusion_engine
        self.top_k = top_k
        self.prompt_manager = prompt_manager

    async def execute(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """执行知识查询"""
        # 1. 向量检索
        docs = await self._search_vector_store(input_data)

        # 2. 知识融合或直接拼接
        context_text = ""
        sources: List[Dict[str, Any]] = []

        if self.fusion_engine and docs:
            try:
                fused = self.fusion_engine.merge(
                    structured_knowledge=[],
                    unstructured_knowledge=docs,
                    query=input_data,
                )
                fused_dict = fused.to_dict() if hasattr(fused, "to_dict") else dict(fused)
                context_text = fused_dict.get("answer", "")
                sources = fused_dict.get("sources", [])
            except Exception as e:
                logger.warning(f"Knowledge fusion failed: {e}, using raw docs")
                context_text, sources = self._format_raw_docs(docs)
        else:
            context_text, sources = self._format_raw_docs(docs)

        # 3. LLM 生成回答
        prompt = self._build_prompt(input_data, context_text)
        response = await self._llm_generate(prompt)

        return SkillResult(
            success=True,
            data={
                "answer": response,
                "sources": sources,
            },
            confidence=0.85 if sources else 0.4,
            metadata={"docs_count": len(sources)},
        )

    async def _fallback(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
        error: Optional[Exception] = None,
    ) -> SkillResult:
        """知识查询降级"""
        return SkillResult(
            success=True,
            data={
                "answer": "知识库查询暂不可用，请稍后再试。",
                "sources": [],
            },
            confidence=0.2,
        )

    async def _search_vector_store(self, query: str) -> List[Dict[str, Any]]:
        """搜索向量知识库"""
        try:
            if asyncio.iscoroutinefunction(self.vector_store.search):
                docs = await self.vector_store.search(query=query, n_results=self.top_k)
            else:
                loop = asyncio.get_event_loop()
                docs = await loop.run_in_executor(
                    None, self.vector_store.search, query, self.top_k
                )
        except Exception as e:
            logger.warning(f"Vector store search failed: {e}")
            return []

        if isinstance(docs, dict):
            return docs.get("results", [])
        return docs if isinstance(docs, list) else []

    def _format_raw_docs(self, docs: List[Dict[str, Any]]) -> tuple:
        """将原始文档格式化为文本和来源"""
        texts = []
        sources = []
        for d in docs:
            text = d.get("text", d.get("content", ""))
            if text:
                texts.append(text)
            sources.append(d.get("metadata", {}))
        return "\n\n".join(texts), sources

    async def _llm_generate(self, prompt: str) -> str:
        """调用 LLM 生成文本（避免阻塞事件循环）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.llm_client.complete, prompt)

    def _build_prompt(self, query: str, context_text: str) -> str:
        """构建 Prompt"""
        if self.prompt_manager:
            return self.prompt_manager.get_prompt(
                "knowledge_query_skill",
                variables={
                    "context": context_text,
                    "query": query,
                },
            )

        return f"""基于以下攻略资料回答用户问题：

## 攻略资料
{context_text}

## 用户问题
{query}

请给出准确、简洁的回答。如果资料不足，请明确说明。"""
