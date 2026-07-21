"""视野分析器"""
from typing import List, Dict, Any, Optional

from post_match_review.analyzers.base import BaseLLMReviewAnalyzer, parse_json_response
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.engines.prompt_builder import PromptBuilder
from post_match_review.domain_types.analysis import AnalysisContext, AnalysisResult, Conclusion
from post_match_review.domain_types.match_data import MatchData
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.analyzers.vision")


class VisionAnalyzer(BaseLLMReviewAnalyzer):
    """视野分析器

    分析守卫放置热力图、关键视野盲区、反野效率。
    视野数据缺失时降低置信度并标注。
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        prompt_builder: Optional[PromptBuilder] = None,
    ) -> None:
        super().__init__(llm_client)
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._vision_data_available = True
        logger.info("视野分析器初始化完成")

    @property
    def phase_name(self) -> str:
        return "vision"

    def build_prompt(
        self,
        match_data: MatchData,
        context: AnalysisContext,
    ) -> List[Dict[str, str]]:
        messages = self._prompt_builder.build(
            match_data=match_data,
            phase=self.phase_name,
            completed_results=context.completed_results,
            iteration_feedback=context.iteration_feedback,
        )

        vision_text = self._format_vision_data(match_data)
        messages[1]["content"] += "\n\n" + vision_text

        return messages

    def parse_response(self, response: str) -> List[Conclusion]:
        parsed = parse_json_response(response)
        conclusions: List[Conclusion] = []

        if parsed:
            # 优先查找 conclusions 键
            if "conclusions" in parsed:
                for item in parsed["conclusions"]:
                    try:
                        conclusions.append(self._parse_conclusion(item))
                    except Exception as e:
                        logger.warning("解析结论失败: %s", str(e))
            # 尝试从 analysis 键中提取结论
            elif "analysis" in parsed:
                analysis_data = parsed["analysis"]
                # 从 analysis 中提取关键发现
                for key, value in analysis_data.items():
                    if isinstance(value, dict) and "conclusion" in value:
                        evidence = []
                        if "evidence" in value:
                            if isinstance(value["evidence"], list):
                                evidence = [str(e) for e in value["evidence"]]
                            else:
                                evidence = [str(value["evidence"])]
                        conclusions.append(Conclusion(
                            title=key.replace("_", " ").title(),
                            content=value.get("conclusion", ""),
                            evidence=evidence,
                            has_evidence=len(evidence) > 0,
                            impact="medium",
                        ))
                # 如果没有找到结构化的 conclusion，尝试将整个 analysis 作为单条结论
                if not conclusions:
                    evidence = []
                    if "evidence" in analysis_data:
                        if isinstance(analysis_data["evidence"], list):
                            evidence = [str(e) for e in analysis_data["evidence"]]
                    conclusions.append(Conclusion(
                        title="视野分析",
                        content=str(analysis_data.get("conclusion", analysis_data)),
                        evidence=evidence,
                        has_evidence=len(evidence) > 0,
                        impact="medium",
                    ))
            else:
                # 尝试将整个 JSON 作为单条结论
                evidence = []
                if "evidence" in parsed:
                    if isinstance(parsed["evidence"], list):
                        evidence = [str(e) for e in parsed["evidence"]]
                conclusions.append(Conclusion(
                    title="分析结果",
                    content=str(parsed),
                    evidence=evidence,
                    has_evidence=len(evidence) > 0,
                    impact="medium",
                ))
        else:
            conclusions = self._parse_conclusions_from_text(response)

        return conclusions

    def validate_result(self, result: AnalysisResult) -> bool:
        # 视野数据缺失时降低验证标准
        if not self._vision_data_available:
            return result.confidence >= 0.4 and len(result.conclusions) > 0
        return super().validate_result(result)

    def _parse_conclusion(self, data: Dict[str, Any]) -> Conclusion:
        evidence_list = data.get("evidence", [])
        if isinstance(evidence_list, dict):
            evidence = [str(v) for v in evidence_list.values()]
        elif isinstance(evidence_list, list):
            evidence = [str(e) for e in evidence_list]
        else:
            evidence = []

        return Conclusion(
            title=data.get("title", "未命名结论"),
            content=data.get("content", data.get("finding", "")),
            evidence=evidence,
            has_evidence=len(evidence) > 0,
            impact=data.get("impact", "medium"),
            suggestion=data.get("suggestion"),
        )

    def _parse_conclusions_from_text(self, text: str) -> List[Conclusion]:
        conclusions: List[Conclusion] = []
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        for i, para in enumerate(paragraphs[:5]):
            if len(para) < 20:
                continue
            lines = para.split("\n")
            title = lines[0][:50] if lines else f"结论 {i+1}"
            content = "\n".join(lines[1:]) if len(lines) > 1 else para
            conclusions.append(Conclusion(
                title=title, content=content,
                evidence=[], has_evidence=False, impact="medium",
            ))
        return conclusions

    def _format_vision_data(self, match_data: MatchData) -> str:
        parts: List[str] = []
        parts.append("## 视野数据")
        parts.append("")

        raw = match_data.raw_metadata

        # 检查视野数据是否可用
        vision_data = raw.get("vision", {})
        if not vision_data:
            self._vision_data_available = False
            parts.append("> **注意**: 视野数据不可用，分析将基于推断和有限信息。")
            parts.append("")
            # 提供有限的视野相关信息
            parts.append("### 可用信息")
            parts.append(f"- 比赛时长: {match_data.duration // 60} 分钟")
            parts.append(f"- 游戏模式: {match_data.game_mode}")
            parts.append("")
            return "\n".join(parts)

        self._vision_data_available = True

        # 守卫放置数据
        if "obs" in vision_data:
            parts.append("### 守卫放置（Observer）")
            obs_data = vision_data["obs"]
            if isinstance(obs_data, dict):
                for account_id, placements in obs_data.items():
                    if isinstance(placements, list):
                        parts.append(f"- 玩家 {account_id}: {len(placements)} 个守卫")
                    elif isinstance(placements, int):
                        parts.append(f"- 玩家 {account_id}: {placements} 个守卫")
            parts.append("")

        if "sen" in vision_data:
            parts.append("### 守卫放置（Sentry）")
            sen_data = vision_data["sen"]
            if isinstance(sen_data, dict):
                for account_id, placements in sen_data.items():
                    if isinstance(placements, list):
                        parts.append(f"- 玩家 {account_id}: {len(placements)} 个真眼")
                    elif isinstance(placements, int):
                        parts.append(f"- 玩家 {account_id}: {placements} 个真眼")
            parts.append("")

        # 反野效率相关
        if "life_state" in raw:
            parts.append("### 生命状态数据")
            parts.append(f"- 数据点数量: {len(raw['life_state'])}")
            parts.append("")

        return "\n".join(parts)
