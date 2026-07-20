"""决策点分析器"""
from typing import List, Dict, Any, Optional

from post_match_review.analyzers.base import BaseLLMReviewAnalyzer, parse_json_response
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.engines.prompt_builder import PromptBuilder
from post_match_review.types.analysis import AnalysisContext, Conclusion
from post_match_review.types.match_data import MatchData
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.analyzers.decision")


class DecisionAnalyzer(BaseLLMReviewAnalyzer):
    """决策点分析器

    分析 Roshan 时机、推塔节奏、团战发起/撤退等关键决策。
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        prompt_builder: Optional[PromptBuilder] = None,
    ) -> None:
        super().__init__(llm_client)
        self._prompt_builder = prompt_builder or PromptBuilder()
        logger.info("决策点分析器初始化完成")

    @property
    def phase_name(self) -> str:
        return "decisions"

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

        # 追加决策相关的全量数据摘要
        decision_text = self._format_decision_data(match_data)
        messages[1]["content"] += "\n\n" + decision_text

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
                        title="决策分析",
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

    def _format_decision_data(self, match_data: MatchData) -> str:
        parts: List[str] = []
        parts.append("## 决策分析数据")
        parts.append("")

        # 比赛时间线与关键事件
        duration_min = match_data.duration // 60
        parts.append(f"### 比赛概况")
        parts.append(f"- 总时长: {duration_min} 分钟")
        parts.append(f"- 总击杀: {match_data.radiant_score + match_data.dire_score}")
        parts.append(f"- 胜利方: {'天辉' if match_data.radiant_win else '夜魇'}")
        parts.append("")

        # 团战时间线（作为决策点参考）
        if match_data.teamfight_data:
            parts.append("### 团战时间线（决策点参考）")
            for i, tf in enumerate(match_data.teamfight_data, 1):
                minutes = tf.start // 60
                seconds = tf.start % 60
                winner = "天辉" if tf.radiant_gold_delta > tf.dire_gold_delta else "夜魇"
                parts.append(
                    f"- 团战 {i} ({minutes}:{seconds:02d}): "
                    f"{tf.deaths} 死亡, 优势方 {winner} "
                    f"(经济差 {tf.radiant_gold_delta - tf.dire_gold_delta:+d})"
                )
            parts.append("")

        # 玩家表现摘要（用于评估决策质量）
        parts.append("### 玩家表现摘要")
        for player in match_data.players:
            if player.is_user:
                kda = f"{player.kills}/{player.deaths}/{player.assists}"
                parts.append(f"- **用户** ({player.hero_name}): KDA {kda}, GPM {player.gpm}")
                parts.append(f"  - 英雄伤害: {player.hero_damage}, 塔伤: {player.tower_damage}")
        parts.append("")

        # 原始元数据中的关键事件
        raw = match_data.raw_metadata
        if "objectives" in raw:
            parts.append("### 关键目标事件")
            for obj in raw["objectives"][:10]:
                obj_type = obj.get("type", "unknown")
                time_min = obj.get("time", 0) // 60
                parts.append(f"- {time_min} 分钟: {obj_type}")
            parts.append("")

        return "\n".join(parts)
