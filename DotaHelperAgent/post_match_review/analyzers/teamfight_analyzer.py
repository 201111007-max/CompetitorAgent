"""团战分析器"""
from typing import List, Dict, Any, Optional

from post_match_review.analyzers.base import BaseLLMReviewAnalyzer, parse_json_response
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.engines.prompt_builder import PromptBuilder
from post_match_review.domain_types.analysis import AnalysisContext, Conclusion
from post_match_review.domain_types.match_data import MatchData, TeamfightData
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.analyzers.teamfight")


class TeamfightAnalyzer(BaseLLMReviewAnalyzer):
    """团战分析器

    分析团战参与率、技能释放时机、走位站位等。
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        prompt_builder: Optional[PromptBuilder] = None,
    ) -> None:
        super().__init__(llm_client)
        self._prompt_builder = prompt_builder or PromptBuilder()
        logger.info("团战分析器初始化完成")

    @property
    def phase_name(self) -> str:
        return "teamfight"

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

        if match_data.teamfight_data:
            tf_text = self._format_teamfight_data(match_data.teamfight_data, match_data)
            messages[1]["content"] += "\n\n" + tf_text

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
                        title="团战分析",
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

    def _format_teamfight_data(
        self,
        teamfights: List[TeamfightData],
        match_data: MatchData,
    ) -> str:
        parts: List[str] = []
        parts.append("## 团战数据")
        parts.append("")

        player_map: Dict[str, str] = {}
        for player in match_data.players:
            if player.account_id:
                player_map[player.account_id] = player.hero_name

        for i, tf in enumerate(teamfights, 1):
            minutes = tf.start // 60
            seconds = tf.start % 60
            duration = tf.end - tf.start
            parts.append(f"### 团战 {i} ({minutes}:{seconds:02d}, 持续 {duration}s)")
            parts.append(f"- 死亡人数: {tf.deaths}")
            parts.append(f"- 天辉经济变化: {tf.radiant_gold_delta:+d}")
            parts.append(f"- 夜魇经济变化: {tf.dire_gold_delta:+d}")
            participants = [player_map.get(pid, pid) for pid in tf.players[:6]]
            parts.append(f"- 参与英雄: {', '.join(participants)}")
            parts.append("")

        # 汇总统计
        total_fights = len(teamfights)
        total_deaths = sum(tf.deaths for tf in teamfights)
        radiant_total_delta = sum(tf.radiant_gold_delta for tf in teamfights)
        parts.append("### 团战汇总")
        parts.append(f"- 总团战次数: {total_fights}")
        parts.append(f"- 总死亡人数: {total_deaths}")
        parts.append(f"- 天辉团战总经济变化: {radiant_total_delta:+d}")
        parts.append("")

        return "\n".join(parts)
