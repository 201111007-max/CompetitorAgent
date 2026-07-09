"""阵容分析 Skill

结合数据驱动的阵容分析和 LLM 自然语言生成，提供阵容优劣势解读。
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from ..base import BaseSkill, SkillContext, SkillResult

logger = logging.getLogger(__name__)


class LineupAnalyzerSkill(BaseSkill):
    """阵容分析 Skill

    输入: {"radiant_heroes": [...], "dire_heroes": [...]}
    输出: {"analysis": "自然语言分析", "structured": {...}, "confidence": 0.85}
    """

    def __init__(
        self,
        llm_client: Any,
        hero_analyzer: Optional[Any] = None,
        prompt_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name="lineup_analyzer",
            version="1.0.0",
            description="分析敌我双方阵容的优劣势",
            **kwargs,
        )
        self.llm_client = llm_client
        self.hero_analyzer = hero_analyzer
        self.prompt_manager = prompt_manager

    async def execute(
        self,
        input_data: Dict[str, List[str]],
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """执行阵容分析"""
        radiant = input_data.get("radiant_heroes", [])
        dire = input_data.get("dire_heroes", [])

        # 1. 获取结构化数据（复用现有 analyzer）
        structured: Dict[str, Any] = {}
        if self.hero_analyzer:
            try:
                if asyncio.iscoroutinefunction(self.hero_analyzer.analyze_team_composition):
                    structured = await self.hero_analyzer.analyze_team_composition(radiant, dire)
                else:
                    structured = self.hero_analyzer.analyze_team_composition(radiant, dire)
            except Exception as e:
                logger.warning(f"HeroAnalyzer failed: {e}, using LLM only")

        # 2. 构造 Prompt
        prompt = self._build_prompt(radiant, dire, structured)

        # 3. LLM 生成自然语言分析
        response = await self._llm_generate(prompt)

        return SkillResult(
            success=True,
            data={
                "analysis": response,
                "structured": structured,
                "radiant_heroes": radiant,
                "dire_heroes": dire,
            },
            confidence=0.85 if structured else 0.7,
            metadata={"has_structured_data": bool(structured)},
        )

    async def _fallback(
        self,
        input_data: Dict[str, List[str]],
        context: Optional[SkillContext] = None,
        error: Optional[Exception] = None,
    ) -> SkillResult:
        """降级到规则驱动分析"""
        radiant = input_data.get("radiant_heroes", [])
        dire = input_data.get("dire_heroes", [])

        if self.hero_analyzer:
            try:
                if asyncio.iscoroutinefunction(self.hero_analyzer.analyze_team_composition):
                    structured = await self.hero_analyzer.analyze_team_composition(radiant, dire)
                else:
                    structured = self.hero_analyzer.analyze_team_composition(radiant, dire)

                return SkillResult(
                    success=True,
                    data={
                        "analysis": structured.get("conclusion", "阵容分析暂不可用"),
                        "structured": structured,
                        "radiant_heroes": radiant,
                        "dire_heroes": dire,
                    },
                    confidence=0.5,
                )
            except Exception:
                pass

        return SkillResult(
            success=True,
            data={
                "analysis": f"阵容分析暂不可用。己方英雄数：{len(radiant)}，敌方英雄数：{len(dire)}",
                "structured": {},
                "radiant_heroes": radiant,
                "dire_heroes": dire,
            },
            confidence=0.3,
        )

    async def _llm_generate(self, prompt: str) -> str:
        """调用 LLM 生成文本（避免阻塞事件循环）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.llm_client.complete, prompt)

    def _build_prompt(
        self,
        radiant: List[str],
        dire: List[str],
        structured: Dict[str, Any],
    ) -> str:
        """构建 Prompt"""
        if self.prompt_manager:
            return self.prompt_manager.get_prompt(
                "lineup_analysis",
                variables={
                    "radiant_heroes": "、".join(radiant),
                    "dire_heroes": "、".join(dire),
                    "structured_analysis": json.dumps(structured, ensure_ascii=False),
                },
            )

        return f"""你是一名专业的 Dota 2 阵容分析专家。

## 己方阵容
{"、".join(radiant) if radiant else "暂无"}

## 敌方阵容
{"、".join(dire) if dire else "暂无"}

## 数据参考
{json.dumps(structured, ensure_ascii=False)}

请分析双方阵容优劣势，包括：
1. 己方阵容优势（控制、爆发、推进、分推等）
2. 己方阵容劣势（被克制、缺少某些能力）
3. 敌方阵容优势
4. 敌方阵容劣势
5. 关键对决点
6. 整体胜率评估

请用简洁清晰的语言输出，控制在 300 字以内。"""
