"""DreamRecap 模块 - 复盘后整合与持久化"""
import json
from typing import Any, Dict, List, Optional

from post_match_review.interfaces.llm import ILLMClient
from post_match_review.prompt.loader import get_prompt_loader
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.memory.dream_recap")


class DreamRecap:
    """复盘后整合与持久化"""

    def __init__(
        self,
        llm_client: ILLMClient,
        persistent_notes: Any,
        skill_store: Any,
    ) -> None:
        self._llm_client = llm_client
        self._persistent_notes = persistent_notes
        self._skill_store = skill_store
        self._prompt_loader = get_prompt_loader()

    async def integrate(
        self,
        match_data: Any,
        report: Any,
        quality_assessment: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """整合复盘发现并持久化"""
        try:
            insights = await self._extract_insights(match_data, report)
            patterns = await self._identify_patterns(insights)

            result = {
                "insights": insights,
                "patterns": patterns,
                "persisted_notes": 0,
                "persisted_skills": 0,
            }

            for pattern in patterns:
                if pattern.get("confidence", 0) >= 0.7:
                    if pattern.get("type") == "skill":
                        await self._persist_skill(pattern)
                        result["persisted_skills"] += 1
                    else:
                        await self._persist_note(pattern)
                        result["persisted_notes"] += 1

            logger.info(
                f"DreamRecap 整合完成: "
                f"insights={len(insights)}, "
                f"patterns={len(patterns)}, "
                f"notes={result['persisted_notes']}, "
                f"skills={result['persisted_skills']}"
            )

            return result

        except Exception as e:
            logger.error(f"DreamRecap 整合失败: {e}", exc_info=True)
            return {
                "insights": [],
                "patterns": [],
                "persisted_notes": 0,
                "persisted_skills": 0,
                "error": str(e),
            }

    async def _extract_insights(
        self,
        match_data: Any,
        report: Any,
    ) -> List[Dict[str, Any]]:
        """提取关键发现"""
        prompt = self._build_insights_prompt(match_data, report)

        try:
            response = await self._llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )

            insights = self._parse_insights_response(response)
            return insights

        except Exception as e:
            logger.error(f"提取洞察失败: {e}")
            raise  # 重新抛出异常，让 integrate 方法捕获

    async def _identify_patterns(
        self,
        insights: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """识别可复用模式"""
        if not insights:
            return []

        prompt = self._build_patterns_prompt(insights)

        try:
            response = await self._llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )

            patterns = self._parse_patterns_response(response)
            return patterns

        except Exception as e:
            logger.error(f"识别模式失败: {e}")
            return []

    async def _persist_note(self, pattern: Dict[str, Any]) -> None:
        """持久化为笔记"""
        await self._persistent_notes.add_note(
            category=pattern.get("category", "general"),
            content=pattern.get("content", ""),
            evidence=pattern.get("evidence", []),
            metadata={
                "confidence": pattern.get("confidence", 0.5),
                "source_match": pattern.get("source_match"),
            },
        )

    async def _persist_skill(self, pattern: Dict[str, Any]) -> None:
        """持久化为技能"""
        name = pattern.get("name", "unnamed_skill")
        content = pattern.get("content", "")

        self._skill_store.save_skill(
            name=name,
            content=content,
            metadata={
                "description": pattern.get("description", ""),
                "confidence": pattern.get("confidence", 0.5),
                "source_match": pattern.get("source_match"),
                "tags": pattern.get("tags", []),
            },
        )

    def _build_insights_prompt(
        self,
        match_data: Any,
        report: Any,
    ) -> str:
        """构建洞察提取提示词"""
        # 从 YAML 模板加载
        system_prompt = self._prompt_loader.render(
            "dream_recap",
            "insight_extraction.system",
        )
        user_prompt = self._prompt_loader.render(
            "dream_recap",
            "insight_extraction.user",
            duration=getattr(match_data, "duration", "N/A"),
            winner="Radiant" if getattr(match_data, "radiant_win", False) else "Dire",
            report_summary=self._summarize_report(report),
        )
        return f"{system_prompt}\n\n{user_prompt}"

    def _build_patterns_prompt(self, insights: List[Dict[str, Any]]) -> str:
        """构建模式识别提示词"""
        insights_text = "\n".join(
            [f"- {i.get('insight', '')} (category={i.get('category', '')})" for i in insights]
        )
        
        # 从 YAML 模板加载
        system_prompt = self._prompt_loader.render(
            "dream_recap",
            "pattern_recognition.system",
        )
        user_prompt = self._prompt_loader.render(
            "dream_recap",
            "pattern_recognition.user",
            insights_list=insights_text,
        )
        return f"{system_prompt}\n\n{user_prompt}"

    def _summarize_report(self, report: Any) -> str:
        """简化报告摘要"""
        if hasattr(report, "summary"):
            return report.summary
        if hasattr(report, "conclusions"):
            return "\n".join(report.conclusions[:5])
        return "无摘要"

    def _parse_json_list_response(self, response: str) -> List[Dict[str, Any]]:
        """通用 JSON 列表响应解析
        
        支持从 markdown 代码块中提取 JSON。
        """
        try:
            text = response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            return json.loads(text.strip())
        except Exception as e:
            logger.error(f"解析 JSON 列表响应失败: {e}")
            return []

    def _parse_insights_response(self, response: str) -> List[Dict[str, Any]]:
        """解析洞察响应"""
        return self._parse_json_list_response(response)

    def _parse_patterns_response(self, response: str) -> List[Dict[str, Any]]:
        """解析模式响应"""
        return self._parse_json_list_response(response)
