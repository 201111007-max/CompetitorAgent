"""经济分析器"""
from typing import List, Dict, Any, Optional

from post_match_review.analyzers.base import BaseLLMReviewAnalyzer, parse_json_response
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.engines.prompt_builder import PromptBuilder
from post_match_review.domain_types.analysis import AnalysisContext, Conclusion
from post_match_review.domain_types.match_data import MatchData, EconomyData
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.analyzers.economy")


class EconomyAnalyzer(BaseLLMReviewAnalyzer):
    """经济分析器

    分析 GPM/XPM 曲线、装备购买效率、关键装备时间节点。
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        prompt_builder: Optional[PromptBuilder] = None,
    ) -> None:
        super().__init__(llm_client)
        self._prompt_builder = prompt_builder or PromptBuilder()
        logger.info("经济分析器初始化完成")

    @property
    def phase_name(self) -> str:
        return "economy"

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

        if match_data.economy_data:
            eco_text = self._format_economy_data(match_data.economy_data, match_data)
            messages[1]["content"] += "\n\n" + eco_text

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
                        title="经济分析",
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

    def _format_economy_data(
        self,
        economy_data: EconomyData,
        match_data: MatchData,
    ) -> str:
        parts: List[str] = []
        parts.append("## 经济数据")
        parts.append("")

        player_map: Dict[str, str] = {}
        user_account_id: Optional[str] = None
        for player in match_data.players:
            if player.account_id:
                player_map[player.account_id] = player.hero_name
            if player.is_user and player.account_id:
                user_account_id = player.account_id

        # GPM/XPM 摘要
        parts.append("### GPM/XPM 摘要")
        for account_id, gpm_series in economy_data.gpm_series.items():
            hero_name = player_map.get(account_id, account_id)
            xpm_series = economy_data.xpm_series.get(account_id, [])
            avg_gpm = sum(gpm_series) // len(gpm_series) if gpm_series else 0
            avg_xpm = sum(xpm_series) // len(xpm_series) if xpm_series else 0
            peak_gpm = max(gpm_series) if gpm_series else 0
            marker = " **(用户)**" if account_id == user_account_id else ""
            parts.append(
                f"- {hero_name}{marker}: 平均 GPM {avg_gpm}, "
                f"平均 XPM {avg_xpm}, 峰值 GPM {peak_gpm}"
            )
        parts.append("")

        # 净经济曲线关键点
        if economy_data.networth_series:
            parts.append("### 净经济变化趋势")
            for account_id, nw_series in economy_data.networth_series.items():
                hero_name = player_map.get(account_id, account_id)
                if len(nw_series) >= 3:
                    early = nw_series[len(nw_series) // 4]
                    mid = nw_series[len(nw_series) // 2]
                    late = nw_series[-1]
                    parts.append(
                        f"- {hero_name}: 前期 {early}, 中期 {mid}, 后期 {late}"
                    )
            parts.append("")

        # 购买记录摘要
        if economy_data.purchase_log:
            parts.append("### 关键购买记录")
            for account_id, purchases in economy_data.purchase_log.items():
                hero_name = player_map.get(account_id, account_id)
                if purchases:
                    item_names = [p.get("key", p.get("name", "unknown")) for p in purchases[:5]]
                    parts.append(f"- {hero_name}: {', '.join(item_names)}")
            parts.append("")

        return "\n".join(parts)
