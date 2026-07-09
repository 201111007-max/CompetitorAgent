"""智能搜索 Skill

基于搜索引擎获取最新 Dota 2 信息，并用 LLM 生成摘要回答。
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from ..base import BaseSkill, SkillContext, SkillResult

logger = logging.getLogger(__name__)


class WebSearchSkill(BaseSkill):
    """智能搜索 Skill

    输入: 搜索关键词
    输出: {"answer": "自然语言摘要", "sources": [...]}
    """

    def __init__(
        self,
        llm_client: Any,
        search_engine: Any,
        max_results: int = 5,
        prompt_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name="web_search",
            version="1.0.0",
            description="搜索最新 Dota 2 信息并生成摘要",
            **kwargs,
        )
        self.llm_client = llm_client
        self.search_engine = search_engine
        self.max_results = max_results
        self.prompt_manager = prompt_manager

    async def execute(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """执行智能搜索"""
        query = f"Dota 2 {input_data}"

        # 1. 搜索
        results = await self._do_search(input_data)

        # 2. LLM 摘要
        results_text = self._format_results(results)
        prompt = self._build_prompt(input_data, results_text)
        response = await self._llm_generate(prompt)

        return SkillResult(
            success=True,
            data={
                "answer": response,
                "sources": [
                    {"title": r.get("title", ""), "url": r.get("url", r.get("href", ""))}
                    for r in results
                ],
            },
            confidence=0.75 if results else 0.3,
            metadata={"result_count": len(results)},
        )

    async def _fallback(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
        error: Optional[Exception] = None,
    ) -> SkillResult:
        """搜索降级"""
        return SkillResult(
            success=True,
            data={
                "answer": "搜索功能暂不可用，请稍后再试。",
                "sources": [],
            },
            confidence=0.2,
        )

    async def _do_search(self, query: str) -> List[Dict[str, Any]]:
        """执行搜索"""
        try:
            # 尝试调用异步搜索
            if asyncio.iscoroutinefunction(self.search_engine.search):
                search_result = await self.search_engine.search(query, max_results=self.max_results)
            else:
                # 兼容 Tool 实例的 execute 方法
                if hasattr(self.search_engine, "execute"):
                    loop = asyncio.get_event_loop()
                    tool_result = await loop.run_in_executor(
                        None, self.search_engine.execute, query, self.max_results
                    )
                    search_result = tool_result.data if hasattr(tool_result, "data") else tool_result
                else:
                    loop = asyncio.get_event_loop()
                    search_result = await loop.run_in_executor(
                        None, self.search_engine.search, query, self.max_results
                    )
        except Exception as e:
            logger.warning(f"Search engine failed: {e}")
            return []

        if isinstance(search_result, dict):
            return search_result.get("results", [])
        return search_result if isinstance(search_result, list) else []

    def _format_results(self, results: List[Dict[str, Any]]) -> str:
        """格式化搜索结果"""
        lines = []
        for r in results:
            title = r.get("title", "")
            snippet = r.get("snippet", r.get("body", ""))
            url = r.get("url", r.get("href", ""))
            lines.append(f"标题：{title}\n摘要：{snippet}\n链接：{url}")
        return "\n\n".join(lines) if lines else "（无搜索结果）"

    async def _llm_generate(self, prompt: str) -> str:
        """调用 LLM 生成文本（避免阻塞事件循环）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.llm_client.complete, prompt)

    def _build_prompt(self, query: str, results_text: str) -> str:
        """构建 Prompt"""
        if self.prompt_manager:
            return self.prompt_manager.get_prompt(
                "web_search_skill",
                variables={
                    "results": results_text,
                    "query": query,
                },
            )

        return f"""基于以下搜索结果回答用户问题：

## 搜索结果
{results_text}

## 用户问题
{query}

请给出简洁准确的回答，并标注信息来源。如果搜索结果为空或不足，请明确说明。"""
