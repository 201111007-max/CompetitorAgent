"""版本强势查询 Skill

基于大数据统计返回当前版本热门/强势英雄，并用 LLM 生成自然语言总结。
"""

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from ..base import BaseSkill, SkillContext, SkillResult

logger = logging.getLogger(__name__)


class MetaAnalyzerSkill(BaseSkill):
    """版本强势查询 Skill

    输入: 用户查询字符串（如"当前版本哪些英雄强势？"）
    输出: {"answer": "自然语言回答", "meta_heroes": [...]}
    """

    def __init__(
        self,
        llm_client: Any,
        data_fetcher: Callable[[], Awaitable[Dict[str, Any]]],
        prompt_manager: Optional[Any] = None,
        cache_ttl: int = 3600,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name="meta_analyzer",
            version="1.0.0",
            description="查询当前版本热门/强势英雄",
            **kwargs,
        )
        self.llm_client = llm_client
        self.data_fetcher = data_fetcher
        self.prompt_manager = prompt_manager
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_time: float = 0.0
        self._cache_ttl = cache_ttl

    async def execute(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """执行版本强势查询"""
        meta_data = await self._fetch_meta_data()

        prompt = self._build_prompt(input_data, meta_data)
        response = await self._llm_generate(prompt)

        return SkillResult(
            success=True,
            data={
                "answer": response,
                "meta_heroes": meta_data.get("meta_heroes", []),
            },
            confidence=0.8 if meta_data.get("meta_heroes") else 0.5,
            metadata={"hero_count": len(meta_data.get("meta_heroes", []))},
        )

    async def _fallback(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
        error: Optional[Exception] = None,
    ) -> SkillResult:
        """降级到简单列表输出"""
        meta_data = await self._fetch_meta_data()
        heroes = meta_data.get("meta_heroes", [])

        if heroes:
            names = [h.get("hero_name", "未知") for h in heroes[:10]]
            answer = f"当前版本强势英雄（按胜率+选取率排序）：{', '.join(names)}"
        else:
            answer = "版本数据暂不可用，请稍后再试。"

        return SkillResult(
            success=True,
            data={
                "answer": answer,
                "meta_heroes": heroes,
            },
            confidence=0.4,
        )

    async def _fetch_meta_data(self) -> Dict[str, Any]:
        """获取版本数据（带缓存）"""
        now = time.time()
        if self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        data = await self.data_fetcher()
        self._cache = data
        self._cache_time = now
        return data

    async def _llm_generate(self, prompt: str) -> str:
        """调用 LLM 生成文本（避免阻塞事件循环）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.llm_client.complete, prompt)

    def _build_prompt(self, query: str, meta_data: Dict[str, Any]) -> str:
        """构建 Prompt"""
        heroes = meta_data.get("meta_heroes", [])[:20]
        heroes_text = json.dumps(heroes, ensure_ascii=False, indent=2)
        if self.prompt_manager:
            return self.prompt_manager.get_prompt(
                "meta_query",
                variables={
                    "meta_data": heroes_text,
                    "user_query": query,
                },
            )

        return f"""你是一名 Dota 2 版本分析师。

## 当前版本数据
{heroes_text}

## 用户问题
{query}

请根据版本数据回答用户问题，控制在 200 字以内。"""
